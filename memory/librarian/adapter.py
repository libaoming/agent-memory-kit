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
    """写本地 memory/store/*.md，frontmatter 对齐 retrieval 的字段期望。

    更新语义 = 版本化 claim（非覆盖）：同一条记忆被再次写入且内容有实质变化时，
    不直接抹掉旧 claim，而是把它归档进正文的「## 历史 claim」段、frontmatter 记 version/
    supersedes。当前 frontmatter/正文永远是最新视图（检索只看它），旧态留在正文可 diff。
    borrow 自 N71 的 bitemporal claim：更新≠遗忘，「事实变了」与「事实错了」都留痕。
    """

    HISTORY_HEADER = "## 历史 claim（版本化 · 非覆盖）"

    def __init__(self, store_dir: str):
        self.store_dir = os.path.expanduser(store_dir)
        os.makedirs(self.store_dir, exist_ok=True)

    def write_page(self, title: str, content: str, metadata: dict) -> str:
        path = os.path.join(self.store_dir, f"{_slug(title)}.md")
        meta = {
            "title": title,
            "type": metadata.get("type", "lesson"),
            "summary": metadata.get("summary", ""),
            "tags": metadata.get("tags", ""),
            "updated": metadata.get("updated", date.today().isoformat()),
        }

        # 版本化 claim：同名已存在且有实质变化 → 归档旧 claim，不覆盖
        history = ""
        prior = self._read_prior(path)
        if prior is not None:
            changed = not (prior["current"].strip() == content.strip()
                           and prior["meta"].get("summary", "") == meta["summary"])
            if changed:
                prev_v = int(prior["meta"].get("version", "1") or "1")
                meta["version"] = prev_v + 1
                old_summary = prior["meta"].get("summary", "") or prior["current"][:80]
                meta["supersedes"] = old_summary[:60]
                if metadata.get("contradiction"):
                    meta["contradiction"] = "true"
                old_conf = prior["meta"].get("confidence", "")
                conf_tag = f" ⟨conf {old_conf}⟩" if old_conf else ""
                reason = metadata.get("change_reason", "(未注明变更原因)")
                entry = (f"- **v{prev_v}** ({prior['meta'].get('updated', '?')}){conf_tag}: "
                         f"{old_summary}\n  ↳ 变更原因: {reason}\n")
                history = entry + prior["history"]  # 最新的旧版排最前
            else:
                # 幂等：内容没变，沿用旧 version 与历史，不制造重复
                if prior["meta"].get("version"):
                    meta["version"] = prior["meta"]["version"]
                history = prior["history"]

        # provenance（出处：来源事件/原文/发话人/URL）+ confidence（置信度 0-1）：
        # 只在 Reflector 给出时才写，避免给无出处的记忆塞空字段。检索端据此带出处、按置信度降权。
        if metadata.get("provenance"):
            meta["provenance"] = metadata["provenance"]
        if metadata.get("confidence") is not None:
            meta["confidence"] = metadata["confidence"]

        fm = "---\n" + "".join(f"{k}: {v}\n" for k, v in meta.items()) + "---\n\n"
        body = content.rstrip() + "\n"
        if history.strip():
            body += f"\n{self.HISTORY_HEADER}\n{history.rstrip()}\n"
        with open(path, "w", encoding="utf-8") as f:
            f.write(fm + body)
        return path

    def _read_prior(self, path: str):
        """读旧版记忆，拆成 {meta, current(当前 claim 正文), history(已有历史段)}；无则 None。"""
        if not os.path.exists(path):
            return None
        txt = open(path, encoding="utf-8", errors="replace").read()
        meta, body = {}, txt
        if txt.startswith("---"):
            end = txt.find("\n---", 3)
            if end != -1:
                for line in txt[3:end].splitlines():
                    m = re.match(r"^(\w+):\s*(.*)$", line)
                    if m:
                        meta[m.group(1)] = m.group(2).strip().strip('"').strip("'")
                body = txt[end + 4:].lstrip("\n")
        idx = body.find(self.HISTORY_HEADER)
        if idx != -1:
            after = body[idx + len(self.HISTORY_HEADER):].lstrip("\n")
            return {"meta": meta, "current": body[:idx].rstrip(), "history": after}
        return {"meta": meta, "current": body.rstrip(), "history": ""}

    def update_index(self) -> None:
        # retrieval 用 FTS5 自建索引，这里无需手动维护目录；保留以满足接口
        pass

    def commit(self, message: str) -> None:
        # 留给上层 git，或在 harness 的 Stop hook 里统一提交
        pass
