# audit/ — hash-chain 防篡改审计链 ✅ ready

记忆四角色的「可追溯」底座：给 **Store 的每次写盘**挂一条 append-only 的签名链，
让「这条记忆什么时候、被谁、以什么动作写进来的」可审、可验、改一个字节就露馅。

蓝本是 Block 开源的 [buzz](https://github.com/block/buzz) 的 `buzz-audit` crate
（agent 与人共用同一条 hash-chain 审计日志）—— 本模块把那套机制搬到 kit 的本地文件场景，
纯标准库、零 pip 依赖。

## 机制

```
genesis(0×64) ← entry0.hash ← entry1.hash ← entry2.hash ← ...
```

每条 entry 存 `prev_hash`（指向前一条的 hash），自己的 `hash` 覆盖
`seq · ts · action · actor · target · canonical(meta) · prev_hash`。
`canonical` 用 `sort_keys`（对齐 buzz 的 `BTreeMap`），保证同一 meta 的哈希跨进程可复现。

`verify_chain()` 从 genesis 重算全链，返回 `(ok, 坏点seq或总数, 原因)`：

| 篡改方式 | 如何被抓 |
|---|---|
| 只改内容不改 hash | 该条重算哈希 ≠ 存储值，当场检出 |
| 改中间条并重算其 hash | 它后一条的 `prev_hash` 仍指旧 hash，下一条断链检出 |
| 删/插中间条 | `prev_hash` 或 `seq` 对不上，断链检出 |
| 改**最后一条**并重算 hash | 无后续锚 → 需外部锚定 `head_hash()`（buzz-audit 亦然） |

## 用法

```python
from audit import AuditLog
from adapter import LocalMarkdownAdapter

audit = AuditLog("~/mystore/.audit.jsonl")
store = LocalMarkdownAdapter("~/mystore", audit=audit)   # 传入即接线，不传=行为字节级不变

store.write_page("开场-录音告知", "首句先告知录音。", {"summary": "..."})  # 自动 append 一条审计
ok, n, reason = audit.verify_chain()                     # (True, 1, "ok")
print(audit.head_hash())                                 # 链尾哈希，定期外锚可闭合"最后一条"缺口
```

`action` 取值：`memory_write` / `memory_update` / `memory_delete` / `reflect_run` / `evolve_step`。

## 测试

```bash
python3 test_audit.py          # 单元：genesis/篡改检出/删条/哈希可复现/非法action  (7/7)
python3 test_adapter_audit.py  # 集成：审计真接进 write_page + audit=None 向后兼容  (5/5)
```

退出码即判定（0=全过），可直接进 features.json 的 `verify`。

## 边界

- 单文件、单写者（进程内 `threading.Lock`）；跨进程并发写需外部文件锁（buzz 用 `pg_advisory_lock`，此处从简）。
- 「最后一条」的完整性需外部锚定 `head_hash()`——这是 hash-chain 的固有性质，非本实现缺陷。
- 反哺方向：delphi-clone 的 `daily_runs` 审计表（ADR-0037，现为纯 append-only 无链）可套同一模式升级为防篡改链。
