"""运行参数的本地持久化存储。"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from pathlib import Path

from ..constants import PARAMETER_FIELDS
from ..settings import PROJECT_ROOT

DEFAULT_PATH = PROJECT_ROOT / "data" / "parameters.json"
_KNOWN_KEYS = tuple(field.key for field in PARAMETER_FIELDS)


class ParameterStoreError(Exception):
    """运行参数读取或保存失败。"""


class ParameterStore:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path is not None else DEFAULT_PATH

    def load(self) -> dict[str, float]:
        if not self.path.exists():
            return {}

        try:
            raw = self.path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ParameterStoreError(f"读取失败：{exc}") from exc

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ParameterStoreError(f"文件内容不是合法 JSON：{exc}") from exc
        if not isinstance(data, dict):
            raise ParameterStoreError("文件格式应为 JSON 对象。")

        values: dict[str, float] = {}
        for key in _KNOWN_KEYS:
            if key not in data:
                continue
            value = data[key]
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                continue
            values[key] = float(value)
        return values

    def save(self, values: Mapping[str, float]) -> None:
        payload: dict[str, float] = {}
        for key in _KNOWN_KEYS:
            if key not in values:
                continue
            value = values[key]
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                continue
            payload[key] = value

        text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temp_path = self.path.with_name(self.path.name + ".tmp")
            temp_path.write_text(text, encoding="utf-8")
            os.replace(temp_path, self.path)
        except OSError as exc:
            raise ParameterStoreError(f"保存失败：{exc}") from exc
