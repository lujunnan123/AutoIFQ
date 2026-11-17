"""子线程代理：接口取 IP、解析、按线程分配。"""

from __future__ import annotations

import json
import os
import random
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable
from urllib.parse import (
    parse_qs,
    quote,
    urlencode,
    urlsplit,
    urlunsplit,
)

import requests

from ..settings import PROJECT_ROOT

DEFAULT_PATH = PROJECT_ROOT / "data" / "proxy_settings.json"
_IP_PORT_RE = re.compile(
    r"(?:(?P<scheme>https?|socks5)://)?"
    r"(?:(?P<user>[^\s:@/]+):(?P<pw>[^\s@/]+)@)?"
    r"(?P<host>(?:\d{1,3}\.){3}\d{1,3}):(?P<port>\d{2,5})",
    re.IGNORECASE,
)
_IP_PORT_AUTH_RE = re.compile(
    r"^(?:(?P<scheme>https?|socks5)://)?"
    r"(?P<host>(?:\d{1,3}\.){3}\d{1,3}):"
    r"(?P<port>\d{2,5}):"
    r"(?P<user>[^:\s]+):(?P<pw>[^\s]+)$",
    re.IGNORECASE,
)

LogFn = Callable[[str, str], None]


class ProxyProviderError(Exception):
    """代理接口请求或解析失败。"""


class ProxyStoreError(Exception):
    """代理设置读取或保存失败。"""


@dataclass(frozen=True)
class ProxySettings:
    enabled: bool = False
    api_url: str = ""
    fetch_count: int = 5
    timeout_sec: float = 20.0


@dataclass(frozen=True)
class ProxyEndpoint:
    server: str
    username: str = ""
    password: str = field(default="", repr=False)

    def as_playwright(self) -> dict[str, str]:
        proxy: dict[str, str] = {"server": self.server}
        if self.username:
            proxy["username"] = self.username
            proxy["password"] = self.password
        return proxy

    def requests_proxies(self) -> dict[str, str]:
        url = self.server
        if self.username:
            parsed = urlsplit(self.server)
            auth = (
                f"{quote(self.username, safe='')}:"
                f"{quote(self.password, safe='')}@"
            )
            url = urlunsplit(
                (
                    parsed.scheme or "http",
                    auth + (parsed.netloc or ""),
                    parsed.path,
                    parsed.query,
                    parsed.fragment,
                )
            )
        return {"http": url, "https": url}

    def display(self) -> str:
        suffix = "（认证）" if self.username else ""
        return f"{self.server}{suffix}"


class ProxyStore:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path is not None else DEFAULT_PATH

    def load(self) -> ProxySettings:
        if not self.path.exists():
            return ProxySettings()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ProxyStoreError(f"读取失败：{exc}") from exc
        if not isinstance(data, dict):
            raise ProxyStoreError("代理设置格式应为 JSON 对象。")

        enabled = bool(data.get("enabled", False))
        api_url = str(data.get("api_url") or "").strip()
        try:
            fetch_count = int(data.get("fetch_count", 5))
        except (TypeError, ValueError):
            fetch_count = 5
        try:
            timeout_sec = float(data.get("timeout_sec", 20.0))
        except (TypeError, ValueError):
            timeout_sec = 20.0
        return ProxySettings(
            enabled=enabled,
            api_url=api_url,
            fetch_count=max(1, min(fetch_count, 50)),
            timeout_sec=max(3.0, min(timeout_sec, 120.0)),
        )

    def save(self, settings: ProxySettings) -> None:
        payload = {
            "enabled": bool(settings.enabled),
            "api_url": str(settings.api_url).strip(),
            "fetch_count": max(1, min(int(settings.fetch_count), 50)),
            "timeout_sec": max(3.0, min(float(settings.timeout_sec), 120.0)),
        }
        text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temp_path = self.path.with_name(self.path.name + ".tmp")
            temp_path.write_text(text, encoding="utf-8")
            os.replace(temp_path, self.path)
        except OSError as exc:
            raise ProxyStoreError(f"保存失败：{exc}") from exc


def fetch_proxies(
    settings: ProxySettings,
    log: LogFn | None = None,
) -> list[ProxyEndpoint]:
    """从代理接口获取一批 IP；接口请求本身保持直连。"""
    log = log or (lambda message, level: None)
    api_url = settings.api_url.strip()
    if not api_url:
        raise ProxyProviderError("未填写代理接口地址。")

    url = _with_fetch_count(api_url, settings.fetch_count)
    session = requests.Session()
    session.trust_env = False
    try:
        response = session.get(
            url,
            timeout=max(3.0, settings.timeout_sec),
            headers={"User-Agent": "AutoIFQ/1.0"},
        )
    except requests.RequestException as exc:
        raise ProxyProviderError(f"代理接口请求失败：{exc}") from exc
    finally:
        session.close()

    if response.status_code != 200:
        raise ProxyProviderError(
            f"代理接口返回 HTTP {response.status_code}"
        )
    text = response.text.strip()
    if not text:
        raise ProxyProviderError("代理接口返回为空。")

    if any(
        cue in text
        for cue in ("白名单", "请先添加", "未授权", "认证失败")
    ):
        raise ProxyProviderError(
            f"代理接口提示：{text[:200]}"
        )

    proxies = _parse_proxy_text(text)
    if not proxies:
        preview = " ".join(text.split())[:160]
        raise ProxyProviderError(f"未解析到代理 IP：{preview}")
    log(f"代理接口获取到 {len(proxies)} 个 IP。", "info")
    return proxies


class ProxyPool:
    """线程安全地分发随机代理；一批用完后重新向接口获取。"""

    def __init__(
        self,
        settings: ProxySettings,
        log: LogFn | None = None,
    ) -> None:
        self._settings = settings
        self._log = log or (lambda message, level: None)
        self._proxies: list[ProxyEndpoint] = []
        self._lock = threading.Lock()

    def acquire(self) -> ProxyEndpoint:
        with self._lock:
            if not self._proxies:
                proxies = fetch_proxies(self._settings, self._log)
                random.shuffle(proxies)
                self._proxies = proxies
            if not self._proxies:
                raise ProxyProviderError("代理池为空。")
            return self._proxies.pop()


def _with_fetch_count(api_url: str, count: int) -> str:
    try:
        parts = urlsplit(api_url)
    except ValueError as exc:
        raise ProxyProviderError(f"代理接口地址不合法：{exc}") from exc
    if parts.scheme not in ("http", "https"):
        raise ProxyProviderError("代理接口地址必须是 http(s) 地址。")
    query = parse_qs(parts.query, keep_blank_values=True)
    query["num"] = [str(max(1, int(count)))]
    return urlunsplit(
        (
            parts.scheme,
            parts.netloc,
            parts.path,
            urlencode(query, doseq=True),
            parts.fragment,
        )
    )


def _parse_proxy_text(text: str) -> list[ProxyEndpoint]:
    proxies: list[ProxyEndpoint] = []
    seen: set[tuple[str, str]] = set()

    for raw_line in re.split(r"[\r\n;,]+", text):
        line = raw_line.strip()
        if not line:
            continue
        auth_match = _IP_PORT_AUTH_RE.fullmatch(line)
        if auth_match:
            endpoint = _endpoint_from_match(auth_match)
            key = (endpoint.server, endpoint.username)
            if key not in seen:
                seen.add(key)
                proxies.append(endpoint)
            continue

        for match in _IP_PORT_RE.finditer(line):
            endpoint = _endpoint_from_match(match)
            if endpoint is None:
                continue
            key = (endpoint.server, endpoint.username)
            if key in seen:
                continue
            seen.add(key)
            proxies.append(endpoint)
    return proxies


def _endpoint_from_match(match: re.Match) -> ProxyEndpoint | None:
    host = match.group("host")
    port = match.group("port")
    scheme = (match.groupdict().get("scheme") or "http").lower()
    if not host or not port:
        return None
    server = f"{scheme}://{host}:{port}"
    user = match.groupdict().get("user") or ""
    password = match.groupdict().get("pw") or ""
    return ProxyEndpoint(
        server=server,
        username=str(user),
        password=str(password),
    )
