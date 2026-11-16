"""询问话术的本地持久化存储。"""

from __future__ import annotations

import json
import os
from collections.abc import Iterable
from pathlib import Path

from ..settings import PROJECT_ROOT

DEFAULT_PATH = PROJECT_ROOT / "data" / "phrases.json"


class PhraseStoreError(Exception):
    """询问话术读取或保存失败。"""


class PhraseStore:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path is not None else DEFAULT_PATH

    def load(self) -> list[str]:
        if not self.path.exists():
            return []

        try:
            raw = self.path.read_text(encoding="utf-8")
        except OSError as exc:
            raise PhraseStoreError(f"读取失败：{exc}") from exc

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise PhraseStoreError(f"文件内容不是合法 JSON：{exc}") from exc

        if isinstance(data, dict):
            data = data.get("phrases")
        if not isinstance(data, list):
            raise PhraseStoreError("文件格式应为字符串数组。")

        phrases: list[str] = []
        for item in data:
            if not isinstance(item, str):
                continue
            value = item.strip()
            if value:
                phrases.append(value)
        return phrases

    def save(self, phrases: Iterable[str]) -> None:
        values: list[str] = []
        for phrase in phrases:
            if not isinstance(phrase, str):
                continue
            value = phrase.strip()
            if value:
                values.append(value)

        payload = json.dumps(values, ensure_ascii=False, indent=2) + "\n"
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temp_path = self.path.with_name(self.path.name + ".tmp")
            temp_path.write_text(payload, encoding="utf-8")
            os.replace(temp_path, self.path)
        except OSError as exc:
            raise PhraseStoreError(f"保存失败：{exc}") from exc
