"""咨询商家列表与勾选状态的本地缓存。"""

from __future__ import annotations

import json
import os
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from ..settings import PROJECT_ROOT

DEFAULT_PATH = PROJECT_ROOT / "data" / "merchants.json"


class MerchantStoreError(Exception):
    """咨询商家缓存读取或保存失败。"""


@dataclass(frozen=True)
class MerchantCache:
    merchants: tuple[str, ...]
    selected: tuple[str, ...]


class MerchantStore:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path is not None else DEFAULT_PATH

    def load(self) -> MerchantCache | None:
        if not self.path.exists():
            return None

        try:
            raw = self.path.read_text(encoding="utf-8")
        except OSError as exc:
            raise MerchantStoreError(f"读取失败：{exc}") from exc

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise MerchantStoreError(
                f"文件内容不是合法 JSON：{exc}"
            ) from exc
        if not isinstance(data, dict):
            raise MerchantStoreError("文件格式应为 JSON 对象。")

        merchants = self._clean_list(data.get("merchants"))
        selected = [
            name for name in self._clean_list(data.get("selected"))
            if name in merchants
        ]
        return MerchantCache(tuple(merchants), tuple(selected))

    def save(
        self,
        merchants: Iterable[str],
        selected: Iterable[str],
    ) -> None:
        merchant_values = self._clean_list(merchants)
        selected_values = [
            name
            for name in self._clean_list(selected)
            if name in merchant_values
        ]
        payload = {
            "merchants": merchant_values,
            "selected": selected_values,
        }
        text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"

        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temp_path = self.path.with_name(self.path.name + ".tmp")
            temp_path.write_text(text, encoding="utf-8")
            os.replace(temp_path, self.path)
        except OSError as exc:
            raise MerchantStoreError(f"保存失败：{exc}") from exc

    @staticmethod
    def _clean_list(values: object) -> list[str]:
        if not isinstance(values, (list, tuple, set)):
            return []
        cleaned: list[str] = []
        seen: set[str] = set()
        for item in values:
            if not isinstance(item, str):
                continue
            value = item.strip()
            if not value or value in seen:
                continue
            seen.add(value)
            cleaned.append(value)
        return cleaned
