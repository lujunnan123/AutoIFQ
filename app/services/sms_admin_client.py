"""短信后台协议客户端：登录并查询指定号码的最新收件短信。"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping

import requests
import urllib3

from ..settings import SmsAdminSettings


class SmsAdminError(Exception):
    """短信后台请求失败。"""


def _parse_timestamp(value: str) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None

    # 兼容 Unix 时间戳（秒或毫秒）。
    try:
        numeric = float(text)
    except ValueError:
        numeric = None
    if numeric is not None:
        if numeric > 1e11:
            numeric /= 1000.0
        if 1e9 <= numeric <= 5e9:
            return numeric
        return None

    normalized = text.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized).timestamp()
    except ValueError:
        pass
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y/%m/%d %H:%M:%S",
    ):
        try:
            return datetime.strptime(text, fmt).timestamp()
        except ValueError:
            continue
    return None


@dataclass(frozen=True)
class SmsMessage:
    id: str
    sender: str
    recipient: str
    content: str
    created_at: str
    received_at: str
    raw: Mapping[str, Any] = field(repr=False, compare=False)

    @property
    def server_timestamp(self) -> float:
        """「服务器收到」时间（created_at），缺失时退回设备收到时间。"""
        return _parse_timestamp(self.created_at) or _parse_timestamp(
            self.received_at
        ) or 0.0

    def identity(self) -> str:
        if self.id:
            return f"id:{self.id}"
        return f"{self.created_at}|{self.received_at}|{self.content}"

    def delay_seconds(self) -> int | None:
        created = _parse_timestamp(self.created_at)
        received = _parse_timestamp(self.received_at)
        if created is None or received is None:
            return None
        return max(0, int(created - received))


class SmsAdminClient:
    """线程安全的短信后台客户端（共享一个会话与 Token）。"""

    def __init__(self, config: SmsAdminSettings) -> None:
        self._config = config
        self._lock = threading.Lock()
        self._token: str | None = None

        self._session = requests.Session()
        self._session.verify = config.verify_ssl
        self._session.headers.update(
            {
                "Accept": "application/json",
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0 Safari/537.36"
                ),
            }
        )
        if not config.verify_ssl:
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    # ------------------------------------------------------------------
    # 认证
    # ------------------------------------------------------------------

    def login(self) -> None:
        with self._lock:
            self._login_unlocked()

    def _login_unlocked(self) -> None:
        if not self._config.username or not self._config.password:
            raise SmsAdminError(
                "短信后台账号未配置（config.json 的 sms_admin.username/password）。"
            )
        url = f"{self._config.base_url}/admin/login"
        try:
            response = self._session.post(
                url,
                json={
                    "username": self._config.username,
                    "password": self._config.password,
                },
                timeout=self._config.request_timeout,
            )
        except requests.RequestException as exc:
            raise SmsAdminError(f"短信后台连接失败：{exc}") from exc

        if response.status_code != 200:
            raise SmsAdminError(f"短信后台登录失败：HTTP {response.status_code}")
        try:
            body = response.json()
        except ValueError as exc:
            raise SmsAdminError("短信后台登录响应不是合法 JSON") from exc

        if body.get("code") not in (0, None):
            message = body.get("message") or body.get("msg") or "未知错误"
            raise SmsAdminError(f"短信后台登录失败：{message}")

        data = body.get("data") or {}
        token = data.get("token")
        if not token:
            raise SmsAdminError("短信后台登录失败：响应中缺少 token")
        self._token = str(token)

    # ------------------------------------------------------------------
    # 短信查询
    # ------------------------------------------------------------------

    def latest_messages(self, phone: str, page_size: int = 20) -> list[SmsMessage]:
        """返回该收件号码的最新收件短信（新到旧）。"""
        body = self._request(
            "GET",
            "/admin/sms",
            params={
                "direction": "in",
                "page": 1,
                "page_size": max(1, page_size),
                "to_number": phone,
            },
        )
        data = body.get("data") or {}
        items = data.get("list") or []
        messages = [
            SmsMessage(
                id=str(item.get("id") or item.get("sms_id") or ""),
                sender=str(item.get("phone_number") or ""),
                recipient=str(
                    item.get("to_number") or item.get("device_phone") or phone
                ),
                content=str(item.get("content") or ""),
                created_at=str(item.get("created_at") or ""),
                received_at=str(item.get("received_at") or ""),
                raw=item,
            )
            for item in items
            if isinstance(item, dict)
        ]
        # 按服务器收到时间新到旧；时间缺失时保留接口返回顺序。
        indexed = list(enumerate(messages))
        indexed.sort(
            key=lambda pair: (pair[1].server_timestamp, -pair[0]), reverse=True
        )
        return [message for _index, message in indexed]

    def _request(self, method: str, path: str, **kwargs) -> dict:
        with self._lock:
            if not self._token:
                self._login_unlocked()
            return self._request_unlocked(method, path, retry_auth=True, **kwargs)

    def _request_unlocked(
        self, method: str, path: str, retry_auth: bool, **kwargs
    ) -> dict:
        url = f"{self._config.base_url}{path}"
        headers = {"Authorization": f"Bearer {self._token}"}
        try:
            response = self._session.request(
                method,
                url,
                headers=headers,
                timeout=self._config.request_timeout,
                **kwargs,
            )
        except requests.RequestException as exc:
            raise SmsAdminError(f"短信后台请求失败：{exc}") from exc

        if response.status_code == 401 and retry_auth:
            self._token = None
            self._login_unlocked()
            return self._request_unlocked(method, path, retry_auth=False, **kwargs)

        if response.status_code != 200:
            raise SmsAdminError(f"短信后台请求失败：HTTP {response.status_code}")

        try:
            body = response.json()
        except ValueError as exc:
            raise SmsAdminError("短信后台响应不是合法 JSON") from exc

        if body.get("code") not in (0, None):
            message = body.get("message") or body.get("msg") or "未知错误"
            raise SmsAdminError(f"短信后台查询失败：{message}")
        return body
