"""螃蟹平台（PXB7）协议客户端：验证码登录并读取用户信息。"""

from __future__ import annotations

import base64
import uuid
from dataclasses import dataclass
from typing import Any

import requests

from ..settings import Pxb7Settings

try:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import padding
except ImportError:  # 纯协议登录密码加密依赖
    serialization = None
    padding = None

# 页面登录页使用的固定 RSA 公钥（JSEncrypt / PKCS#1 v1.5，输出十六进制）。
PXB7_PUBLIC_KEY = """-----BEGIN PUBLIC KEY-----
MFwwDQYJKoZIhvcNAQEBBQADSwAwSAJBALzXtsdrRN7TZWmQkWCT7XQj+SGpCTJS
4stPSwtwLcDcvjIdqyiNLN6P65fw1jY7iVcx2vhjlqpJ3zrKs+/stR8CAwEAAQ==
-----END PUBLIC KEY-----"""

if serialization is not None:
    _RSA_PUBLIC_KEY = serialization.load_pem_public_key(PXB7_PUBLIC_KEY.encode())
else:
    _RSA_PUBLIC_KEY = None


class Pxb7Error(Exception):
    """螃蟹平台请求失败。"""


class Pxb7LoginError(Pxb7Error):
    def __init__(self, message: str, err_code: str = "", retryable: bool = False) -> None:
        super().__init__(message)
        self.err_code = err_code
        self.retryable = retryable


class Pxb7NetworkError(Pxb7Error):
    """网络或响应格式异常。"""


@dataclass(frozen=True)
class Pxb7LoginResult:
    token: str
    user_id: str
    username: str
    warning: str | None = None


class Pxb7Client:
    """一个实例对应一个手机号的一次登录会话。"""

    def __init__(self, config: Pxb7Settings, phone: str) -> None:
        self._config = config
        self._phone = phone
        self._session = requests.Session()
        self._device_id = uuid.uuid5(
            uuid.NAMESPACE_URL, f"autoifq:{phone}"
        ).hex
        self._base_headers = {
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "Origin": config.website,
            "Referer": f"{config.website}/login",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0 Safari/537.36"
            ),
            "client_type": "0",
            "os_type": "5",
            "device_id": self._device_id,
            "gio_device": "-",
            "user_id": "",
        }

    # ------------------------------------------------------------------
    # 登录
    # ------------------------------------------------------------------

    def login_with_code(self, phone: str, code: str) -> Pxb7LoginResult:
        body = self._post(
            "/user/web/login/twiceLogin",
            {
                "phone": phone,
                "validCode": code,
                "countryCode": self._config.country_code,
                "loginType": 2,
            },
        )

        data = body.get("data") or {}
        return self.complete_login(data)

    def login_with_password(
        self, account: str, password: str, yd_token: str
    ) -> Pxb7LoginResult:
        """协议密码登录；yd_token 必须由易盾验证通过后取得。"""
        if not yd_token:
            raise Pxb7Error(
                "缺少易盾 token，无法执行协议密码登录（平台返回：易盾token为空）。"
            )
        body = self._post(
            "/user/web/login/twiceLogin",
            {
                "account": account,
                "password": self.encrypt_password(password),
                "loginType": 1,
                "ydToken": yd_token,
            },
        )
        data = body.get("data") or {}
        return self.complete_login(data)

    @staticmethod
    def encrypt_password(password: str) -> str:
        if _RSA_PUBLIC_KEY is None:
            raise Pxb7Error(
                "缺少 cryptography 依赖，无法加密登录密码。"
                "请执行 pip install cryptography。"
            )
        try:
            ciphertext = _RSA_PUBLIC_KEY.encrypt(
                password.encode("utf-8"), padding.PKCS1v15()
            )
        except ValueError as exc:
            raise Pxb7Error(
                "密码长度超出 RSA 公钥可加密范围，请缩短密码。"
            ) from exc
        # 页面使用 JSEncrypt，默认输出 base64。
        return base64.b64encode(ciphertext).decode("ascii")

    def complete_login(self, data: dict[str, Any]) -> Pxb7LoginResult:
        """使用登录响应 data（协议或浏览器取得）完成 token 换取和用户信息读取。"""
        token = str(data.get("token") or "")
        if not token:
            token = self._resolve_token(data)

        user_id = str(data.get("userId") or data.get("user_id") or "")
        username = str(data.get("nickname") or "")
        warning: str | None = None

        try:
            info = self._fetch_user_info(token)
            username = str(info.get("nickname") or username)
            user_id = str(info.get("userId") or user_id)
        except Pxb7Error as exc:
            warning = f"登录成功，但读取用户信息失败：{exc}"

        return Pxb7LoginResult(
            token=token,
            user_id=user_id,
            username=username,
            warning=warning,
        )

    def load_cookies(self, cookies: list[dict[str, Any]]) -> None:
        """复制浏览器上下文中的 pxb7 cookie，供后续 token 换取使用。"""
        for cookie in cookies:
            domain = str(cookie.get("domain") or "")
            name = str(cookie.get("name") or "")
            if "pxb7.com" not in domain or not name:
                continue
            value = str(cookie.get("value") or "")
            self._session.cookies.set(
                name,
                value,
                domain=domain,
                path=str(cookie.get("path") or "/"),
            )
            if name == "deviceId" and value:
                self._base_headers["device_id"] = value

    def _resolve_token(self, data: dict[str, Any]) -> str:
        """账号可能返回个人/商户身份选择，需要换取实际 token。"""
        user_sign = str(data.get("userSign") or "")
        merchant_sign = str(data.get("merchantSign") or "")

        if user_sign:
            try:
                body = self._post(
                    "/user/web/login/sign2token", {"sign": user_sign}
                )
                token = str((body.get("data") or {}).get("token") or "")
                if token:
                    return token
            except Pxb7LoginError:
                if not merchant_sign:
                    raise

        if merchant_sign:
            body = self._post(
                "/merchant/web/account/queryMerchantToken",
                {"sign": merchant_sign},
            )
            token = str((body.get("data") or {}).get("token") or "")
            if token:
                return token

        keys = ", ".join(sorted(data.keys())) or "空"
        raise Pxb7NetworkError(
            f"登录响应缺少 token，且无法通过身份换取 token（data keys: {keys}）"
        )

    def send_login_code(self, phone: str, yd_token: str | None = None) -> dict[str, Any]:
        """请求发送登录短信。

        平台接口要求易盾 ydToken；未提供时通常会返回「ydToken值为空」。
        本方法仅用于接口自检，界面流程不会自动调用。
        """
        payload: dict[str, Any] = {
            "countryCode": self._config.country_code,
            "phone": phone,
            "businessType": "login",
        }
        if yd_token:
            payload["ydToken"] = yd_token
        return self._post("/user/web/login/sms/sendSms", payload)

    def _fetch_user_info(self, token: str) -> dict[str, Any]:
        body = self._post(
            "/user/web/login/detailInfo",
            {},
            extra_headers={
                "px-authorization-merchant": token,
                "px-authorization-user": token,
            },
        )
        data = body.get("data") or {}
        if not isinstance(data, dict):
            raise Pxb7NetworkError("用户信息响应格式异常")
        return data

    # ------------------------------------------------------------------
    # 请求
    # ------------------------------------------------------------------

    def _post(
        self,
        path: str,
        payload: dict[str, Any],
        extra_headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        url = f"{self._config.base_url}{path}"
        headers = dict(self._base_headers)
        if extra_headers:
            headers.update(extra_headers)

        try:
            response = self._session.post(
                url,
                json=payload,
                headers=headers,
                timeout=self._config.request_timeout,
            )
        except requests.RequestException as exc:
            raise Pxb7NetworkError(f"网络异常：{exc}") from exc

        if response.status_code != 200:
            raise Pxb7NetworkError(f"接口返回 HTTP {response.status_code}")

        try:
            body = response.json()
        except ValueError as exc:
            raise Pxb7NetworkError("接口响应不是合法 JSON") from exc
        if not isinstance(body, dict):
            raise Pxb7NetworkError("接口响应格式异常")

        if not body.get("success"):
            message = str(
                body.get("errMessage") or body.get("msg") or "登录请求失败"
            )
            err_code = str(body.get("errCode") or "")
            retryable = any(
                keyword in message for keyword in ("验证码", "校验码", "动态码", "过期")
            )
            raise Pxb7LoginError(message, err_code=err_code, retryable=retryable)

        return body
