"""test_write_gate.py — MCP 冲突闸（四元组）+ 召回预算闸 集成测试（纯标准库，直接 python3 跑）。

fixture 刻意用【未分词的整句中文 summary】——真实模型输出就是这样，闸门召回必须
靠 shingle 切分才命中；人工分词的 fixture 会让测试证明的比它声称的少。
"""
import json
import os
import shutil
import sys
import tempfile

from server import MemoryMCP
from memory_search import DEFAULT_CONFIG

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
    tmp = tempfile.mkdtemp(prefix="amk_gate_")
    try:
        store_dir = os.path.join(tmp, "store")
        cfg = dict(DEFAULT_CONFIG)
        cfg.update({
            "store_dir": store_dir,
            "db_path": os.path.join(tmp, "idx.db"),
            "max_chars_per_memory": 120,
            "max_total_recall_chars": 2000,  # path 单取独占它，须 > 长记忆正文 640
        })
        srv = MemoryMCP(cfg)

        # ---- 冲突闸（四元组） ----
        r1 = srv.tool_memory_write({
            "title": "开场-录音告知", "content": "通话开始必须先告知本次通话会被录音。",
            "summary": "录音告知是开场红线"})
        check("空 store 首写直接落盘（无候选不拦）", "已写入" in r1)

        r2 = srv.tool_memory_write({
            "title": "通话开头要说明录音", "content": "接通后第一句就要说明本次会录音。",
            "summary": "接通后第一句要说明会录音"})
        check("相似新 title 被冲突闸拦下（未分词中文 summary 也召回）", "冲突闸" in r2)
        check("闸门列出候选旧记忆", "开场-录音告知" in r2)
        check("闸门给全四元组决策", all(k in r2 for k in ("store", "update", "merge", "skip")))

        r2b = srv.tool_memory_write({
            "title": "通话开头要说明录音", "content": "接通后第一句就要说明本次会录音。",
            "summary": "接通后第一句要说明会录音", "dedup_checked": "false"})
        check('字符串 "false" 不绕闸（显式布尔解析）', "冲突闸" in r2b)

        r3 = srv.tool_memory_write({
            "title": "通话开头要说明录音", "content": "接通后第一句就要说明本次会录音。",
            "summary": "接通后第一句要说明会录音", "dedup_checked": True})
        check("判定 store 后（dedup_checked=true）放行", "已写入" in r3)

        r4 = srv.tool_memory_write({
            "title": "开场-录音告知", "content": "告知录音后还应停顿等用户确认。",
            "summary": "录音告知后需等用户确认", "change_reason": "补充确认环节"})
        check("同名再写不过闸（update/merge 走版本化）", "冲突闸" not in r4 and "version 2" in r4)

        # ---- scope 子目录：同 title 在 task/ 下也认账（防 update 死锁 + 根目录重复） ----
        os.makedirs(os.path.join(store_dir, "task"), exist_ok=True)
        with open(os.path.join(store_dir, "task", "夜班-班次确认.md"), "w", encoding="utf-8") as f:
            f.write("---\ntitle: 夜班-班次确认\nsummary: 夜班到岗时间必须二次确认\n"
                    "type: lesson\nupdated: 2026-08-01\n---\n\n夜班到岗时间必须和候选人二次确认。\n")
        srv.store.reindex()
        r5 = srv.tool_memory_write({
            "title": "夜班-班次确认", "content": "夜班到岗时间必须二次确认，并同步给门店。",
            "summary": "夜班班次确认要同步门店", "change_reason": "补同步门店"})
        check("task/ 下同名 → 不拦、版本化（update 不死锁）",
              "冲突闸" not in r5 and "version 2" in r5)
        check("版本化写回原 scope 位置，根目录不造重复",
              os.path.exists(os.path.join(store_dir, "task", "夜班-班次确认.md"))
              and not os.path.exists(os.path.join(store_dir, "夜班-班次确认.md")))

        # ---- slug 碰撞：不同 title 折到同一文件名 → 不得误并 ----
        r6 = srv.tool_memory_write({
            "title": "开场:录音告知", "content": "这是另一条无关的教训。",
            "summary": "完全无关的另一件事情", "dedup_checked": True})
        check("slug 碰撞不误并：原条目 title 未被顶掉", "已写入" in r6 and "version" in r6)
        orig = open(os.path.join(store_dir, "开场-录音告知.md"), encoding="utf-8").read()
        check("原条目 frontmatter title 保持不变", "title: 开场-录音告知" in orig)
        check("碰撞 title 落到加序号的新文件",
              os.path.exists(os.path.join(store_dir, "开场-录音告知-2.md")))

        gate_off = MemoryMCP({**cfg, "dedup_gate": False})
        r7 = gate_off.tool_memory_write({
            "title": "录音相关新条目", "content": "任意内容。", "summary": "又一条录音的教训"})
        check("config dedup_gate=false 可关闸", "已写入" in r7)

        # ---- 召回预算闸（单条 + 总量双预算 + path 单取） ----
        long_body = "预算闸测试正文。" * 80  # 640 字符 > 单条 120
        for i in range(3):
            srv.tool_memory_write({
                "title": f"长记忆样本{i}", "content": long_body,
                "summary": f"预算长文样本{i}", "dedup_checked": True})
        small = MemoryMCP({**cfg, "max_total_recall_chars": 200})
        payload = json.loads(small.tool_memory_search(
            {"query": "预算 长文", "top": 8, "full": True}))
        bodies = [p["body"] for p in payload if "长记忆样本" in p["title"]]
        check("命中全部 3 条长记忆", len(bodies) == 3)
        check("单条预算生效（截断并指路到 path 单取）",
              any("截断" in b and "path=" in b for b in bodies))
        check("总预算生效（尾部条目降级为指针）", any("已用尽" in b for b in bodies))
        suffix_allowance = 180  # 预算管正文本体，指路后缀在外（软预算，见 body_of）
        check("无正文超出 单条预算+后缀余量",
              all(len(b) <= 120 + suffix_allowance for b in bodies))

        one = json.loads(srv.tool_memory_search({"path": "长记忆样本0.md"}))
        check("path 单取独占总预算，拿到完整正文（不再循环截断）",
              len(one["body"]) >= 600 and "截断" not in one["body"])

        idx = json.loads(srv.tool_memory_search({"query": "预算 长文", "top": 3}))
        check("不传 full 仍是轻量 index 行（无 body）", all("body" not in p for p in idx))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\nPASS: {PASS}/{PASS + FAIL}")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
