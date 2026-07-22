"""test_adapter_audit.py — 验证审计链真接进写入口 write_page（非孤岛死代码）。

跑法：python3 test_adapter_audit.py   （退出码自证：0=全过）
"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "librarian"))
from audit import AuditLog          # noqa: E402
from adapter import LocalMarkdownAdapter  # noqa: E402

results = []


def check(name, cond, detail=""):
    results.append((name, cond))
    print(f"  {'✓' if cond else '✗ FAIL'}  {name}{'' if cond else '  → ' + detail}")


d = tempfile.mkdtemp(prefix="amk-int-")
store = os.path.join(d, "store")
audit = AuditLog(os.path.join(d, "audit.jsonl"))
ad = LocalMarkdownAdapter(store, audit=audit)

# 1. 首次写 → 审计 append memory_write
ad.write_page("开场-录音告知", "首句先告知正在录音。", {"summary": "录音告知", "type": "lesson"})
tail = audit.tail()
check("首次 write_page → append memory_write", len(tail) == 1 and tail[0]["action"] == "memory_write",
      f"tail={tail}")

# 2. 同名有实质变化 → 版本化 → 审计记 memory_update
ad.write_page("开场-录音告知", "首句 0.5s 内先告知正在录音，再问是否方便。",
              {"summary": "录音告知(强化)", "type": "lesson", "change_reason": "补时限"})
tail = audit.tail()
check("版本化更新 → append memory_update", len(tail) == 2 and tail[1]["action"] == "memory_update",
      f"tail={[t['action'] for t in tail]}")

# 3. 审计里带 version/supersedes 元数据
check("update entry 带 version=2", tail[1]["meta"].get("version") == 2, f"meta={tail[1]['meta']}")

# 4. 全链 verify ok
ok, n, reason = audit.verify_chain()
check("写盘产生的链 verify=ok", ok and n == 2, f"ok={ok} n={n} reason={reason}")

# 5. 向后兼容：audit=None 时写盘正常、无副作用
d2 = tempfile.mkdtemp(prefix="amk-noaudit-")
ad2 = LocalMarkdownAdapter(os.path.join(d2, "store"))  # 不传 audit
p = ad2.write_page("t", "x", {"summary": "s"})
check("audit=None 写盘照常返回 path", os.path.exists(p), p)

passed = sum(1 for _, c in results if c)
total = len(results)
print(f"\n{'PASS' if passed == total else 'FAIL'}: {passed}/{total}")
sys.exit(0 if passed == total else 1)
