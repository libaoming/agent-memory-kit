"""audit.py — hash-chain 防篡改审计链（记忆四角色的「可追溯」底座）。

纯标准库、零 pip 依赖（守 kit 的核心卖点）。蓝本：Block 开源的 buzz 的 `buzz-audit` crate
（见 Obsidian wiki [[2026-07-22-Buzz产品拆解-agent即成员的事件日志协作平台]]）。

每次记忆写盘 append 一条签名 entry，`prev_hash` 链接前一条，构成 append-only 链：

    genesis(0×64) ← entry0.hash ← entry1.hash ← entry2.hash ← ...

`verify_chain()` 从 genesis 重算全链——任一 entry 的任意字段被事后偷改，
该条的重算哈希就对不上存储值（或它之后一条的 prev_hash 断链），从而定位到坏点。

威胁模型：防的是「事后偷改/删改某条审计记录」。
- 只改内容不改 hash          → 该条 recomputed ≠ stored hash，当场检出。
- 改中间条内容并重算其 hash  → 它后面一条的 prev_hash 仍指向旧 hash，下一条断链检出。
- 改「最后一条」并重算其 hash → 无后续锚，需外部锚定最新 hash（buzz-audit 亦然）。
  用法上把 head_hash() 定期外锚（打印/落他处）即可闭合这一缺口。

哈希覆盖字段（对齐 buzz-audit）：seq · ts(RFC3339) · action · actor · target ·
canonical(meta) · prev_hash。canonical 用 sort_keys 排序（对齐 buzz 的 BTreeMap），
保证同一 meta 的哈希跨进程可复现。
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
from datetime import datetime, timezone

GENESIS_HASH = "0" * 64
_SEP = "\x1f"  # 单元分隔符，避免字段拼接歧义（unit separator）

# 记忆场景的审计动作（对齐写入口的语义；buzz 有 10 个，这里取记忆相关子集）
ACTIONS = frozenset({
    "memory_write",      # 新建一条记忆
    "memory_update",     # 版本化更新（supersede 旧 claim）
    "memory_delete",     # 删除
    "reflect_run",       # 一轮反思批处理
    "evolve_step",       # 一次自动进化迭代
})


def _canonical(meta: dict | None) -> str:
    """meta 规范化 JSON：sort_keys 对齐 buzz-audit 的 BTreeMap，哈希可跨进程复现。"""
    return json.dumps(meta or {}, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _entry_hash(seq: int, ts: str, action: str, actor: str, target: str,
                meta: dict | None, prev_hash: str) -> str:
    payload = _SEP.join([str(seq), ts, action, actor, target, _canonical(meta), prev_hash])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class AuditLog:
    """append-only JSONL 审计链。单文件、单写者（进程内 Lock；无 DB advisory lock 依赖）。"""

    def __init__(self, path: str):
        self.path = os.path.expanduser(path)
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        self._lock = threading.Lock()

    # ---------- 读 ----------
    def _iter_raw(self):
        if not os.path.exists(self.path):
            return
        with open(self.path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    yield json.loads(line)

    def head_hash(self) -> str:
        """链尾哈希（最新 entry 的 hash）；空链返回 genesis。供外部锚定。"""
        last = GENESIS_HASH
        for e in self._iter_raw():
            last = e["hash"]
        return last

    def _count(self) -> int:
        return sum(1 for _ in self._iter_raw())

    def tail(self, n: int = 10) -> list[dict]:
        return list(self._iter_raw())[-n:]

    # ---------- 写 ----------
    def append(self, action: str, actor: str, target: str,
               meta: dict | None = None, ts: str | None = None) -> str:
        """追加一条审计 entry，返回其 hash。ts 可注入（测试确定性用），默认 UTC now。"""
        if action not in ACTIONS:
            raise ValueError(f"未知 action: {action!r}（合法：{sorted(ACTIONS)}）")
        with self._lock:
            seq = self._count()
            prev = self.head_hash()
            ts = ts or datetime.now(timezone.utc).isoformat()
            h = _entry_hash(seq, ts, action, actor, target, meta, prev)
            entry = {
                "seq": seq, "ts": ts, "action": action, "actor": actor,
                "target": target, "meta": meta or {}, "prev_hash": prev, "hash": h,
            }
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            return h

    # ---------- 验 ----------
    def verify_chain(self) -> tuple[bool, int, str]:
        """从 genesis 重算全链。返回 (是否完好, 坏点 seq 或总条数, 原因)。"""
        prev = GENESIS_HASH
        seq = -1
        for seq, e in enumerate(self._iter_raw()):
            if e.get("seq") != seq:
                return (False, seq, f"seq 乱序：存 {e.get('seq')} 期望 {seq}")
            if e.get("prev_hash") != prev:
                return (False, seq, "prev_hash 断链（前一条被改/删或此条被插）")
            recomputed = _entry_hash(seq, e["ts"], e["action"], e["actor"],
                                     e["target"], e.get("meta"), e["prev_hash"])
            if recomputed != e.get("hash"):
                return (False, seq, "内容被篡改（重算哈希不符）")
            prev = e["hash"]
        return (True, seq + 1, "ok")
