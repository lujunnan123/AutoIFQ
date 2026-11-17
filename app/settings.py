"""运行配置加载（短信后台、螃蟹平台、登录等待参数）。"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

if getattr(sys, "frozen", False):
    # PyInstaller 打包后：config/data/output 放在 exe 同目录
    PROJECT_ROOT = Path(sys.executable).resolve().parent
else:
    PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config.json"


class SettingsError(Exception):
    """配置缺失或格式错误。"""


@dataclass(frozen=True)
class SmsAdminSettings:
    base_url: str
    username: str
    password: str = field(repr=False)
    verify_ssl: bool = False
    request_timeout: float = 30.0


@dataclass(frozen=True)
class Pxb7Settings:
    base_url: str = "https://api-pc.pxb7.com/api"
    website: str = "https://www.pxb7.com"
    country_code: str = "86"
    request_timeout: float = 30.0


PXB7_RECOVERY_URL = (
    "https://www.pxb7.com/sell/recovery/game/10371?bizProd=1"
)


@dataclass(frozen=True)
class Pxb7AccountSettings:
    """用于获取三角洲行动咨询商家的螃蟹账号。"""

    phone: str = ""
    password: str = field(default="", repr=False)
    state_path: str = "data/pxb7_state.json"
    browser_channel: str = "msedge"
    headless: bool = True
    login_timeout: float = 120.0
    game_name: str = "三角洲行动"
    recovery_url: str = PXB7_RECOVERY_URL


@dataclass(frozen=True)
class LoginSettings:
    sms_wait_timeout: float = 60.0
    sms_poll_interval: float = 3.0
    sms_latest_count: int = 5
    sms_max_age_seconds: float = 300.0
    sms_keyword: str = "螃蟹账号"
    max_code_attempts: int = 3
    status_log_interval: float = 15.0
    default_password: str = "Aa123456"
    sms_trigger: str = "browser"  # browser / none
    browser_headless: bool = False
    browser_timeout: float = 180.0
    browser_channel: str = "msedge"


@dataclass(frozen=True)
class ExcelSettings:
    copy_limit: int = 5  # 0 表示复制全部记录
    output_dir: str = ""  # 为空时输出到项目 output/ 目录


FEISHU_LOGIN_URL = (
    "https://accounts.feishu.cn/accounts/page/login?app_id=2&no_trap=1"
    "&query_scope=all"
    "&redirect_uri=https%3A%2F%2Fmcnd1pwpmqfu.feishu.cn%2Fbase%2F"
    "CiobbXJADaxgZYszgJ6cYu79nbc%3Ftable%3Dtblb6ULuiNj6hcBF"
    "%26view%3DvewpjEN0P6"
    "&should_pass_through=1&utm_from=organic_ccm_share_web"
    "&force_use_feishu_login=1"
)
FEISHU_TABLE_URL = (
    "https://mcnd1pwpmqfu.feishu.cn/base/CiobbXJADaxgZYszgJ6cYu79nbc"
    "?table=tblb6ULuiNj6hcBF&view=vewpjEN0P6"
)


@dataclass(frozen=True)
class FeishuSettings:
    login_url: str = FEISHU_LOGIN_URL
    table_url: str = FEISHU_TABLE_URL
    tenant_name: str = "杭州维音信息科技公司"
    base_name: str = "Auto测试库"
    table_name: str = "三角洲成品号--小新"
    state_path: str = "data/feishu_state.json"
    browser_channel: str = "msedge"
    login_timeout: float = 300.0
    fetch_headless: bool = True


@dataclass(frozen=True)
class AppSettings:
    sms_admin: SmsAdminSettings
    pxb7: Pxb7Settings
    pxb7_account: Pxb7AccountSettings
    login: LoginSettings
    excel: ExcelSettings
    feishu: FeishuSettings


def _as_float(value, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_int(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_bool(value, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return default


def load_settings(path: str | Path | None = None) -> AppSettings:
    """读取 config.json；短信后台账号可用环境变量覆盖。"""
    config_path = Path(path) if path is not None else DEFAULT_CONFIG_PATH
    raw: dict = {}
    if config_path.exists():
        try:
            raw = json.loads(config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SettingsError(f"配置文件读取失败：{config_path}（{exc}）") from exc
    elif path is not None:
        raise SettingsError(f"配置文件不存在：{config_path}")

    sms_raw = raw.get("sms_admin") or {}
    username = os.getenv("AUTOIFQ_SMS_USERNAME") or str(
        sms_raw.get("username") or ""
    ).strip()
    password = os.getenv("AUTOIFQ_SMS_PASSWORD") or str(
        sms_raw.get("password") or ""
    )

    base_url = str(sms_raw.get("base_url") or "https://ph.hzdaba.com:8899/api").rstrip("/")
    if not base_url.startswith(("http://", "https://")):
        raise SettingsError("sms_admin.base_url 必须是 http(s) 地址。")

    pxb7_raw = raw.get("pxb7") or {}
    pxb7_account_raw = raw.get("pxb7_account") or {}
    login_raw = raw.get("login") or {}
    excel_raw = raw.get("excel") or {}
    feishu_raw = raw.get("feishu") or {}

    return AppSettings(
        sms_admin=SmsAdminSettings(
            base_url=base_url,
            username=username,
            password=password,
            verify_ssl=bool(sms_raw.get("verify_ssl", False)),
            request_timeout=_as_float(sms_raw.get("request_timeout"), 30.0),
        ),
        pxb7=Pxb7Settings(
            base_url=str(
                pxb7_raw.get("base_url") or "https://api-pc.pxb7.com/api"
            ).rstrip("/"),
            website=str(pxb7_raw.get("website") or "https://www.pxb7.com").rstrip("/"),
            country_code=str(pxb7_raw.get("country_code") or "86"),
            request_timeout=_as_float(pxb7_raw.get("request_timeout"), 30.0),
        ),
        pxb7_account=Pxb7AccountSettings(
            phone=str(pxb7_account_raw.get("phone") or "").strip(),
            password=str(pxb7_account_raw.get("password") or ""),
            state_path=str(
                pxb7_account_raw.get("state_path")
                or "data/pxb7_state.json"
            ),
            browser_channel=str(
                pxb7_account_raw.get("browser_channel") or "msedge"
            ).strip(),
            headless=_as_bool(
                pxb7_account_raw.get("headless"), True
            ),
            login_timeout=max(
                30.0,
                _as_float(pxb7_account_raw.get("login_timeout"), 120.0),
            ),
            game_name=str(
                pxb7_account_raw.get("game_name") or "三角洲行动"
            ),
            recovery_url=str(
                pxb7_account_raw.get("recovery_url")
                or PXB7_RECOVERY_URL
            ),
        ),
        excel=ExcelSettings(
            copy_limit=max(0, _as_int(excel_raw.get("copy_limit"), 5)),
            output_dir=str(excel_raw.get("output_dir") or "").strip(),
        ),
        feishu=FeishuSettings(
            login_url=str(feishu_raw.get("login_url") or FEISHU_LOGIN_URL),
            table_url=str(feishu_raw.get("table_url") or FEISHU_TABLE_URL),
            tenant_name=str(
                feishu_raw.get("tenant_name") or "杭州维音信息科技公司"
            ),
            base_name=str(feishu_raw.get("base_name") or "Auto测试库"),
            table_name=str(
                feishu_raw.get("table_name") or "三角洲成品号--小新"
            ),
            state_path=str(
                feishu_raw.get("state_path") or "data/feishu_state.json"
            ),
            browser_channel=str(
                feishu_raw.get("browser_channel") or "msedge"
            ).strip(),
            login_timeout=max(
                30.0, _as_float(feishu_raw.get("login_timeout"), 300.0)
            ),
            fetch_headless=_as_bool(
                feishu_raw.get("fetch_headless"), True
            ),
        ),
        login=LoginSettings(
            sms_wait_timeout=max(
                5.0, _as_float(login_raw.get("sms_wait_timeout"), 60.0)
            ),
            sms_poll_interval=max(
                0.5, _as_float(login_raw.get("sms_poll_interval"), 3.0)
            ),
            sms_latest_count=max(
                1, _as_int(login_raw.get("sms_latest_count"), 5)
            ),
            sms_max_age_seconds=max(
                30.0,
                _as_float(login_raw.get("sms_max_age_seconds"), 300.0),
            ),
            sms_keyword=str(login_raw.get("sms_keyword") or "螃蟹账号"),
            max_code_attempts=max(
                1, _as_int(login_raw.get("max_code_attempts"), 3)
            ),
            status_log_interval=max(
                1.0, _as_float(login_raw.get("status_log_interval"), 15.0)
            ),
            default_password=str(
                login_raw.get("default_password") or "Aa123456"
            ),
            sms_trigger=(
                "browser"
                if str(login_raw.get("sms_trigger") or "browser").lower()
                not in ("none", "off", "disabled")
                else "none"
            ),
            browser_headless=_as_bool(
                login_raw.get("browser_headless"), False
            ),
            browser_timeout=max(
                30.0, _as_float(login_raw.get("browser_timeout"), 180.0)
            ),
            browser_channel=str(
                login_raw.get("browser_channel") or "msedge"
            ).strip(),
        ),
    )
