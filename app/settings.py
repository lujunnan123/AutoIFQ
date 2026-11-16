"""运行配置加载（短信后台、螃蟹平台、登录等待参数）。"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

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


@dataclass(frozen=True)
class AppSettings:
    sms_admin: SmsAdminSettings
    pxb7: Pxb7Settings
    login: LoginSettings
    excel: ExcelSettings


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
    login_raw = raw.get("login") or {}
    excel_raw = raw.get("excel") or {}

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
        excel=ExcelSettings(
            copy_limit=max(0, _as_int(excel_raw.get("copy_limit"), 5)),
            output_dir=str(excel_raw.get("output_dir") or "").strip(),
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
