#!/usr/bin/env python3
"""build_store.py — dogfood：把一个 critic 型 Reflector 的 issue 沉淀进记忆 store。

演示记忆四角色里的一段：Reflector(质检器) → librarian(LocalMarkdownAdapter) → Store，
之后 retrieval/memory_search.py 即可检索，语音 agent 开场前注入「这场景最常踩的坑」。

两种模式：
  python3 build_store.py            # demo：用内置的泛化招聘客服教训（不调 LLM，可重复）
  python3 build_store.py --grade DATE  # 正路：接你自己的质检器跑真通话评分（见下方 build_from_grader）

store 落在 ./store/（被 .gitignore 排除，因可能含真实通话教训）。
"""
import sys
from pathlib import Path

KIT = Path(__file__).resolve().parents[2]          # agent-memory-kit/
sys.path.insert(0, str(KIT / "memory"))
from librarian.adapter import LocalMarkdownAdapter  # noqa: E402
from reflector.evaluator import grader_verdict_adapter  # noqa: E402

STORE_DIR = Path(__file__).resolve().parent / "store"

# 内置泛化教训（招聘语音客服的常见失分点；真实项目里这些由你的质检器从通话中产出）
DEMO_LESSONS = [
    {"scene": "开场-身份告知", "tag": "开场 身份 合规",
     "summary": "开场常忘自报身份——第一句应表明自己是招聘助手"},
    {"scene": "开场-录音告知", "tag": "开场 录音 合规",
     "summary": "通话录音前应先告知用户本次通话会被录音"},
    {"scene": "信息采集-关键槽位", "tag": "采集 班次 流程",
     "summary": "确认区域后要主动追问班次（白班/夜班），别等用户自己说"},
    {"scene": "交互-首句接住", "tag": "交互 自然度",
     "summary": "用户首句要先接住确认听清，再推进，避免答非所问"},
]


def build_demo():
    adapter = LocalMarkdownAdapter(str(STORE_DIR))
    n = 0
    for d in DEMO_LESSONS:
        title = d["scene"]
        content = f"**场景**：{d['scene']}\n\n**教训**：{d['summary']}\n"
        adapter.write_page(title, content,
                           {"type": "lesson", "summary": d["summary"], "tags": d["tag"]})
        n += 1
    print(f"✓ demo：写入 {n} 条教训 → {STORE_DIR}", file=sys.stderr)
    print(f"  下一步索引+检索：python3 ../../memory/retrieval/memory_search.py "
          f'"班次 录音 开场" --config ./memory_config.json --reindex', file=sys.stderr)


def build_from_grader(target_date: str):
    """正路示例：接一个 critic 型质检器（吃 trace、吐 {total,issues,one_line}）→ store。

    把下面的 import 换成你自己的质检器模块即可。它只要满足 reflector/evaluator.py 的
    Verdict 契约（见 grader_verdict_adapter），就能插进记忆闭环。
    """
    try:
        import grade as g  # noqa: E402  ← 替换成你的质检器模块
    except ImportError:
        print("提示：把本函数里的 `import grade` 换成你自己的质检器模块再用 --grade。",
              file=sys.stderr)
        return
    calls = g.load_calls(target_date)
    if not calls:
        print(f"无通话：{target_date}", file=sys.stderr); return
    tmpl = g.load_prompt()
    adapter = LocalMarkdownAdapter(str(STORE_DIR))
    n = 0
    for call in calls:
        grade = g.grade_call(call, tmpl)
        if not grade:
            continue
        verdict = grader_verdict_adapter(grade)
        if not verdict["issues"]:
            continue
        title = f"通话{n+1}｜{verdict['score']}分"
        content = ("**问题**：\n" + "\n".join(f"- {x}" for x in verdict["issues"]) +
                   f"\n\n**小结**：{verdict['one_line']}\n")
        adapter.write_page(title, content,
                           {"type": "call-review", "summary": verdict["one_line"],
                            "tags": " ".join(verdict["issues"][:3])})
        n += 1
    print(f"✓ {target_date} 写入 {n} 条通话复盘 → {STORE_DIR}", file=sys.stderr)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--grade":
        build_from_grader(sys.argv[2] if len(sys.argv) > 2 else "2026-01-01")
    else:
        build_demo()
