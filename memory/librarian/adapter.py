"""adapter.py — 持久层适配器接口 + 内置最简实现。

接口是 P2 占位（重型后端如 Obsidian/Notion 待抽）；但 LocalMarkdownAdapter 是**可用**的：
它把 Reflector 提炼出的教训写成 memory/store/*.md，retrieval/memory_search.py 开箱即能索引，
构成一条不依赖任何外部知识库的最小记忆闭环。
"""
from __future__ import annotations

import os
import re
from datetime import date
from typing import Protocol


class PersistenceAdapter(Protocol):
    def write_page(self, title: str, content: str, metadata: dict) -> str: ...
    def update_index(self) -> None: ...
    def commit(self, message: str) -> None: ...


def _slug(s: str) -> str:
    s = re.sub(r"[^\w一-鿿]+", "-", s.strip())
    return s.strip("-")[:60] or "untitled"


class LocalMarkdownAdapter:
    """写本地 memory/store/*.md，frontmatter 对齐 retrieval 的字段期望。"""

    def __init__(self, store_dir: str):
        self.store_dir = os.path.expanduser(store_dir)
        os.makedirs(self.store_dir, exist_ok=True)

    def write_page(self, title: str, content: str, metadata: dict) -> str:
        meta = {
            "title": title,
            "type": metadata.get("type", "lesson"),
            "summary": metadata.get("summary", ""),
            "tags": metadata.get("tags", ""),
            "updated": metadata.get("updated", date.today().isoformat()),
        }
        fm = "---\n" + "".join(f"{k}: {v}\n" for k, v in meta.items()) + "---\n\n"
        path = os.path.join(self.store_dir, f"{_slug(title)}.md")
        with open(path, "w", encoding="utf-8") as f:
            f.write(fm + content + "\n")
        return path

    def update_index(self) -> None:
        # retrieval 用 FTS5 自建索引，这里无需手动维护目录；保留以满足接口
        pass

    def commit(self, message: str) -> None:
        # 留给上层 git，或在 harness 的 Stop hook 里统一提交
        pass
