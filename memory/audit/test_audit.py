"""test_audit.py — hash-chain 审计链验收（纯标准库，退出码自证：0=全过）。

跑法：python3 test_audit.py
DoD：改任意一条 entry → verify_chain 检出并定位坏点。
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from audit import AuditLog, GENESIS_HASH, _entry_hash  # noqa: E402

FIXED = ["2026-07-22T10:00:00+00:00", "2026-07-22T10:01:00+00:00",
         "2026-07-22T10:02:00+00:00", "2026-07-22T10:03:00+00:00"]


def _fresh():
    d = tempfile.mkdtemp(prefix="amk-audit-")
    return AuditLog(os.path.join(d, "audit.jsonl"))


def _seed(log):
    """写 4 条确定性 entry。"""
    log.append("memory_write", "reflector", "store/开场-录音告知.md",
               {"version": 1, "summary": "首句先告知录音"}, ts=FIXED[0])
    log.append("memory_write", "reflector", "store/交互-首句接住.md",
               {"version": 1, "summary": "0.5s 内接住"}, ts=FIXED[1])
    log.append("memory_update", "reflector", "store/开场-录音告知.md",
               {"version": 2, "supersedes": "首句先告知录音"}, ts=FIXED[2])
    log.append("evolve_step", "evolve", "prompts/recruiter.md",
               {"score": 8.4}, ts=FIXED[3])


def _rewrite(path, rows):
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


results = []


def check(name, cond, detail=""):
    results.append((name, cond, detail))
    print(f"  {'✓' if cond else '✗ FAIL'}  {name}{'' if cond else '  → ' + detail}")


# 1. 正常链 verify ok
log = _fresh(); _seed(log)
ok, n, reason = log.verify_chain()
check("正常链 verify=ok 且 4 条", ok and n == 4, f"ok={ok} n={n} reason={reason}")

# 2. genesis 锚定：第 0 条 prev_hash == 64 个 0
first = list(log._iter_raw())[0]
check("首条 prev_hash = genesis(0×64)", first["prev_hash"] == GENESIS_HASH)

# 3. 篡改：改中间条 target，不改 hash（模拟事后直接改文件）→ 检出
log = _fresh(); _seed(log)
rows = list(log._iter_raw())
rows[1]["target"] = "store/伪造-被塞的记忆.md"
_rewrite(log.path, rows)
ok, bad, reason = log.verify_chain()
check("改中间条内容(不改hash) → 检出且定位=seq1", (not ok) and bad == 1, f"ok={ok} bad={bad} reason={reason}")

# 4. 狡猾篡改：改中间条 target 并重算其 hash → 后一条 prev_hash 断链检出
log = _fresh(); _seed(log)
rows = list(log._iter_raw())
rows[1]["target"] = "store/伪造.md"
rows[1]["hash"] = _entry_hash(1, rows[1]["ts"], rows[1]["action"], rows[1]["actor"],
                              rows[1]["target"], rows[1]["meta"], rows[1]["prev_hash"])
_rewrite(log.path, rows)
ok, bad, reason = log.verify_chain()
check("改中间条+重算hash → 后条断链检出(seq2)", (not ok) and bad == 2 and "prev_hash" in reason,
      f"ok={ok} bad={bad} reason={reason}")

# 5. 删除中间条 → 断链检出
log = _fresh(); _seed(log)
rows = list(log._iter_raw())
del rows[1]
_rewrite(log.path, rows)
ok, bad, reason = log.verify_chain()
check("删中间条 → 检出", not ok, f"ok={ok} bad={bad} reason={reason}")

# 6. 哈希可复现：同参数跨实例 append 出同 hash
a, b = _fresh(), _fresh()
ha = a.append("memory_write", "r", "x.md", {"b": 2, "a": 1}, ts=FIXED[0])
hb = b.append("memory_write", "r", "x.md", {"a": 1, "b": 2}, ts=FIXED[0])  # key 乱序
check("哈希可复现(meta key 顺序无关)", ha == hb, f"{ha[:12]} vs {hb[:12]}")

# 7. 非法 action 拒绝
log = _fresh()
try:
    log.append("rm_rf", "x", "y")
    check("非法 action 被拒", False, "未抛异常")
except ValueError:
    check("非法 action 被拒", True)

passed = sum(1 for _, c, _ in results if c)
total = len(results)
print(f"\n{'PASS' if passed == total else 'FAIL'}: {passed}/{total}")
sys.exit(0 if passed == total else 1)
