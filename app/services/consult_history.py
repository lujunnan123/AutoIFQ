"""手机号与商家的咨询历史，避免同一手机号重复咨询同一商家。"""

from __future__ import annotations

import json
import os
from collections.abc import Iterable, Mapping
from pathlib import Path

from ..settings import PROJECT_ROOT

DEFAULT_PATH = PROJECT_ROOT / "data" / "consult_history.json"


class ConsultHistoryStoreError(Exception):
    """咨询历史读取或保存失败。"""


class ConsultHistoryStore:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path is not None else DEFAULT_PATH

    def load(self) -> dict[str, set[str]]:
        if not self.path.exists():
            return {}

        try:
            raw = self.path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ConsultHistoryStoreError(f"读取失败：{exc}") from exc

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ConsultHistoryStoreError(
                f"文件内容不是合法 JSON：{exc}"
            ) from exc
        if isinstance(data, dict) and isinstance(data.get("phones"), dict):
            data = data["phones"]
        if not isinstance(data, dict):
            raise ConsultHistoryStoreError(
                "文件格式应为「手机号 -> 商家数组」的对象。"
            )

        history: dict[str, set[str]] = {}
        for phone, merchants in data.items():
            if not isinstance(phone, str) or not phone.strip():
                continue
            if not isinstance(merchants, list):
                continue
            values = {
                merchant.strip()
                for merchant in merchants
                if isinstance(merchant, str) and merchant.strip()
            }
            history[phone.strip()] = values
        return history

    def save(self, history: Mapping[str, Iterable[str]]) -> None:
        payload: dict[str, list[str]] = {}
        for phone, merchants in history.items():
            if not isinstance(phone, str) or not phone.strip():
                continue
            values = sorted(
                {
                    merchant.strip()
                    for merchant in merchants
                    if isinstance(merchant, str) and merchant.strip()
                }
            )
            if values:
                payload[phone.strip()] = values

        text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temp_path = self.path.with_name(self.path.name + ".tmp")
            temp_path.write_text(text, encoding="utf-8")
            os.replace(temp_path, self.path)
        except OSError as exc:
            raise ConsultHistoryStoreError(f"保存失败：{exc}") from exc
