"""evaluator.py — critic 型 Reflector 的接口契约（P1 占位 stub）。

本 kit 不提供通用评分实现（维度是业务特定的）。这里只钉契约：
任何质检器只要吃一条 trace、吐一个 Verdict，就能插进记忆闭环，
既作为「记忆该记什么」的依据，也作为 evolve/ 的进化信号。

第一个真实实例是 miaomiao-grader 的 grade.py（grade_call 已几乎吐出 Verdict）。
"""
from __future__ import annotations

from typing import Protocol, TypedDict


class Verdict(TypedDict):
    score: int            # 0-10
    pass_: bool           # score>=7 约定
    issues: list[str]     # 命中的问题（将被 librarian 沉淀进 store）
    one_line: str         # ≤80 字一句话总结


class Evaluator(Protocol):
    """实现这个协议即可接入。trace 结构由项目自定，建议含 messages/transcript。"""

    def evaluate(self, trace: dict) -> Verdict: ...


def grader_verdict_adapter(grade: dict) -> Verdict:
    """把 miaomiao-grader grade_call 的输出规整成 Verdict（P1 接线示例）。"""
    return Verdict(
        score=int(grade.get("total", 0)),
        pass_=int(grade.get("total", 0)) >= 7,
        issues=list(grade.get("issues", [])),
        one_line=str(grade.get("one_line", "")),
    )
