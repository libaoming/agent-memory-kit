# reflector/ — critic 型 Reflector 接口（P1 占位）

记忆四角色里 Reflector 的「评估」一半：读 Doer 的 trace，产出结构化评估（分数 + issue），
作为「记忆该记什么」的依据，也作为 `evolve/` 的进化信号。

## 为什么是占位

评估**维度**是高度业务特定的（招聘的「信息完整度」、客服的「解决率」、答疑的「准确性」各不同），
无法做成开箱即用的通用 rubric。所以本 kit 只定义**接口契约**，具体 critic 由业务方提供。

## 接口契约（`evaluator.py`）

```python
class Evaluator(Protocol):
    def evaluate(self, trace: dict) -> Verdict: ...
# Verdict = {"score": 0-10, "pass": bool, "issues": list[str], "one_line": str}
```

只要你的质检器吃一条 trace、吐这个 Verdict，就能插进来。

## 第一个真实实例：miaomiao-grader

miaomiao-grader 的 `grade.py` 就是一个现成的 critic Reflector：
- 输入：通话 trace（transcript）
- 输出：`{scores{5维}, total, verdict, issues[], one_line}` —— 已经几乎是上面的 Verdict
- 它的 `prompts/judge.md` 评分维度，可直接搬给 `evolve/judge.md` 当进化标尺

**归宿**：grader 不该长期当孤立项目，它应成为本 kit 的 reflector adapter 第一个实例。
P1 的工作 = 把 grader 的 `{scores,issues}` 规整成 `Verdict`，并把它的 issue 导进 `memory/store/`
供 `retrieval` 检索（见 `examples/recruit-voice-runtime/`）。
