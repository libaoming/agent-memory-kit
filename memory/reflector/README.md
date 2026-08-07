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

## 读 trace 的两条取证纪律（borrow 自 qm）

reflector 是第一个碰 trace 的角色。**幻觉一旦混进 `issues`，后面 librarian 再怎么提炼也救不回来**——
它只会被写成一条措辞更漂亮的假记忆。所以下面两条不是建议，是 Evaluator 实现必须满足的契约。
两条都 borrow 自 `yc-software/qm` 的 `src/memory/strategies/per-turn.ts`（2026-08-01 读源码）。

### 1. 偏好只能来自当事人自己的话

**偏好、意图、指令，只有当事人在这段 trace 里自己说了才算数。绝不能从 Doer 自己的回复里推导。**

Doer 说「按用户偏好，我静默排队以免刷屏」——这**不是**任何人持有该偏好的证据，那只是 Doer 在
描述自己的策略。同样排除对未在场者的二手转述（「他应该会想要 X」）。

违反这条的后果是**自我强化幻觉**：Doer 编的理由 → 被记成用户的偏好 → 下一轮注入回 Doer →
成为既定事实，且再也无法被证伪。记忆系统会自己把自己喂坏。

对应到接口：`Verdict.issues` 里任何一条关于「人想要什么」的判断，必须能在 trace 中指到
当事人的原话；指不到就不许出现在 issues 里。

### 2. 无人说话的自主轮次，禁止产出关于人的结论

cron / watcher / 定时任务触发的轮次没有人说话——trace 里的「输入」是系统或机器人的触发信号，
「输出」是 Doer 独自干活。这种轮次**只准产出操作性事实**（状态、阻塞、队列、结果），
**禁止输出任何关于某个人的偏好 / 意图 / 指令类结论**；若一轮里只有这类结论，正确输出是「什么都不记」。

实现上给 `evaluate` 的 trace 带一个 `autonomous: bool`（或由 actor 是否为 `system:*` 推断），
为真时切换到收窄的评估口径。**有 cron 的 agent 不做这条隔离，跑得越久记忆越脏**——
自主轮次通常远多于真人对话轮次，污染速度是碾压性的。

## 触发策略：warm-up 递增阈值 + idle 兜底（`trigger.py`，borrow 自 TDB）

Reflector **什么时候跑**和「怎么评」同样重要，且这半是通用的，所以给了实现而非占位。
冷启动两难：批处理阈值定高了，新 Doer 跑半天一条记忆没有；定低了，稳态下每条 trace 都打
一次 LLM。TencentDB-Agent-Memory 的 pipeline-manager 解法（已抄成 `trigger.py`，纯逻辑无 IO）：

```
threshold 从 1 起步 → 每成功跑一批翻倍 → 封顶稳态值(默认 5)
  ⇒ 第 1 条 trace 就出第一批记忆，稳态后回到省钱的批处理
idle 兜底(默认 60s)：不足一批但闲置超时也触发——凑不满批的尾巴不会永远等
consolidation_due：librarian 重整 store 的「只提前不推迟」节流
  （有新写入最快 15min 一次，无动静最慢 60min 兜底一次）
```

宿主（cron / Stop hook / daemon）喂 `n_pending` 与 idle 秒数即可：

```python
t = WarmupTrigger()                     # 5 条 / 60s / 15-60min 都可调
if t.should_reflect(n_pending, idle_s): # → 跑 critic+librarian 一批
    ...; t.record_batch_done()          # 成功才推进阈值；失败保持低阈值尽快重试
```

## 第一个真实实例：miaomiao-grader

miaomiao-grader 的 `grade.py` 就是一个现成的 critic Reflector：
- 输入：通话 trace（transcript）
- 输出：`{scores{5维}, total, verdict, issues[], one_line}` —— 已经几乎是上面的 Verdict
- 它的 `prompts/judge.md` 评分维度，可直接搬给 `evolve/judge.md` 当进化标尺

**归宿**：grader 不该长期当孤立项目，它应成为本 kit 的 reflector adapter 第一个实例。
P1 的工作 = 把 grader 的 `{scores,issues}` 规整成 `Verdict`，并把它的 issue 导进 `memory/store/`
供 `retrieval` 检索（见 `examples/recruit-voice-runtime/`）。
