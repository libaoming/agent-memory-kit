"""test_trigger.py — WarmupTrigger 触发策略单测（纯标准库，直接 python3 跑）。"""
import sys

from trigger import WarmupTrigger

PASS = 0
FAIL = 0


def check(name, cond):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✓  {name}")
    else:
        FAIL += 1
        print(f"  ✗  {name}")


def main():
    t = WarmupTrigger(steady_batch=5, idle_seconds=60)

    check("冷启动首条 trace 即触发（阈值=1）", t.should_reflect(1))
    check("0 条 pending 永不触发（含 idle 超时）", not t.should_reflect(0, idle_s=999))

    t.record_batch_done()  # 1 → 2
    check("成功一批后阈值翻倍：1 条不再触发", not t.should_reflect(1))
    check("成功一批后阈值翻倍：2 条触发", t.should_reflect(2))

    t.record_batch_done()  # 2 → 4
    t.record_batch_done()  # 4 → 5（封顶 steady_batch，不到 8）
    check("阈值封顶稳态值 5（4→5 而非 8）", t.threshold == 5)
    t.record_batch_done()
    check("到顶后不再增长", t.threshold == 5)

    check("不足一批但 idle 超时 → 兜底触发", t.should_reflect(1, idle_s=60))
    check("不足一批且未超时 → 不触发", not t.should_reflect(1, idle_s=59))

    check("整理：不足 floor 不跑（有新写入）",
          not t.consolidation_due(14 * 60, has_new_writes=True))
    check("整理：过 floor 且有新写入 → 跑", t.consolidation_due(15 * 60, has_new_writes=True))
    check("整理：无新写入 floor 不跑", not t.consolidation_due(30 * 60, has_new_writes=False))
    check("整理：无新写入但过 ceil → 兜底跑", t.consolidation_due(60 * 60, has_new_writes=False))

    for name, kwargs in [
        ("steady_batch<1 被拒", {"steady_batch": 0}),
        ("idle_seconds<=0 被拒（warm-up 会形同虚设）", {"idle_seconds": 0}),
        ("floor>ceil 被拒（『只提前不推迟』会反转）",
         {"consolidate_floor_s": 3600, "consolidate_ceil_s": 900}),
    ]:
        try:
            WarmupTrigger(**kwargs)
            check(name, False)
        except ValueError:
            check(name, True)

    print(f"\nPASS: {PASS}/{PASS + FAIL}")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
