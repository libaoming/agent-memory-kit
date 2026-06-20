> 🌏 [English](methodology.md) | **中文**

# 方法论：运行时 agent 记忆的四角色

## 起点：Anthropic「第二组 agent 做记忆」

一个反直觉的工程主张：**别让 agent 边干活边记笔记/反思**。原因四条：

1. **上下文污染**：Doer 的 context 已被任务塞满，再叠反思会抢 token、稀释注意力。
2. **自我合理化偏差**：刚做完决策的 agent 评判自己，天然倾向说"对"。
3. **时序错配**：干活要快、要实时；复盘可以慢、可以离线、可以用更便宜的模型。
4. **写入失控**：长期记忆是资产，得有独立闸门，不能让执行者随手改自己的宪法。

所以拆成 **Doer（无状态执行）+ 第二组 agent（评估/提炼）+ 持久记忆层**。这不是新发明，是
actor-critic / generator-evaluator 架构落到 agent 记忆上的工程版（学术对应 Reflexion、
Generative Agents 的「记忆流 + 反思」）。

## 四角色

```
Doer → trace → Reflector(critic + librarian) → Store → 检索注入回 Doer
```

- **Doer**：无状态，每轮临时 context，只管完成任务。
- **Trace**：带轮次顺序的完整轨迹（可读、可重放）。
- **Reflector**：独立 context 的第二组 agent，两职——
  - *critic*：评估这轮干得怎样、哪里错（结构化分数 + issue，不是自由文本）。
  - *librarian*：提炼哪些值得沉淀成长期教训。
- **Store**：结构化持久层，写入经闸门（限量/去重/校准）。
- **检索注入**：下一次 Doer 启动时，按当前任务检索 top-k 注入——不是全量灌。

三个命门：trace 要完整可读、评估要结构化、Doer 与 Reflector 必须隔离 context（甚至不同模型）。

## 两层记忆，别混

| | 谁的记忆 | 工具归属 |
|---|---|---|
| **运行时记忆** | 你 build 的产品 agent | 本 kit |
| **开发时记忆** | Claude Code 跨会话开发协作 | harness-kit 的 STATUS.md / 个人 memory |

本 kit 只管运行时。开发时记忆不要在这里重复造。

## 本 kit 是从四个真实实现抽象出来的

| 角色 | 来源实现 | 通用度 | 本 kit 状态 |
|---|---|---|---|
| 检索注入 | `recall/wiki_search.py` | 90% | ✅ retrieval/（路径/字段/输出格式参数化） |
| 闭环优化 | `claude-sdk-playground/autoevolve` | 95% | ✅ evolve/（load_skill 改依赖注入） |
| critic 评估 | `miaomiao-grader` | 中 | 🟡 reflector/（接口占位，grader 是第一个实例） |
| librarian 持久 | `wiki-autoupdate.sh` | 中 | 🟡 librarian/（接口 + LocalMarkdown 最简实现；Obsidian 待抽） |

为什么只抽两块成现成件：评估维度（招聘 5 维 vs 客服解决率）和持久层 schema（Obsidian vs Notion）
是业务/系统特定的，强行通用化会产出「谁都不好用的抽象层」。所以这两块只钉接口契约，
由业务方填——这是刻意的克制，不是没做完。

## 横向对照：外部 agent memory 产品在解哪道题

「agent memory」是个被滥用的标签，市面同名产品其实在解完全不同的题。用本 kit 的四角色
坐标去拆，差异立刻清楚（三例采于 2026-06-18~19 Hacker News / X）：

| 产品 | 它的「记忆」是什么 | 命中本 kit 哪个角色 | 形态 |
|---|---|---|---|
| **Parcle**（parcle.ai） | 跨 70+ 系统的**业务数据**，建索引后按需检索一小撮 | 几乎全是 **retrieval**（机器全自动，无 reflector/人审） | 闭源 / 企业销售；自报 token −70%、agent 2x、97% 准确 |
| **Draft**（github.com/idodekerobo/draft，MIT） | 团队的**产品决策/上下文**（采自 Slack/Granola/GitHub/会话） | **Capture→Review→Sync→Inject** ≈ Doer trace → **HITL 版 reflector** → librarian(git) → 注入 | 开源 / 本地优先；多 agent（CC/Codex/Cursor/Hermes） |
| **Perplexity Brain in Computer**（2026-06-19 发布） | 跨会话**持续学习**沉淀的「上下文图谱」，给 Computer 建状态、越跑越有状态 | **retrieval（图谱检索）+ 隐式 librarian（自动累积状态）**，仍**无显式 reflector/人审** | 闭源 / Perplexity Max 研究预览 |

三点对本 kit 的设计校验：

1. **Parcle 证明「纯 retrieval」也能成产品**，但它没有 reflector/evolve 冷环——记忆只进不「反思提炼」，
   靠的是数据本身够结构化（企业数仓）。本 kit 面向的是**非结构化经验教训**（踩过的坑），所以
   reflector 不能省，这正是两者分野。
2. **Draft 的 Review 步 = 一个 HITL 版 reflector**：机器提炼出的上下文更新先进 inbox 等人点头才入库。
   本 kit 的 `reflector` 目前是自动评估提炼，若要加「重要记忆人工确认才落库」这档，Draft 的
   inbox + 独立 clone git 同步是可直接抄的工程模式（呼应下文「人的 4 个不可替代锚点」）。
3. **Perplexity Brain 与 Parcle 同属「全自动累积 + 纯检索/图谱」一派**，再次印证：当前能跑成商业产品的
   agent memory，绝大多数砍掉了 reflector 冷环——它们赌的是**数据/交互信号本身够结构化**（企业数仓、
   computer-use 操作轨迹、知识图谱），靠量取胜，不做「反思提炼」。本 kit 的分野因此更清楚：面向
   **非结构化经验教训**（踩过的坑、判错的边界）时，缺了 critic 评估这道工序，记忆只会越积越噪、
   检索召回越来越脏——reflector 不是可选项而是命门。三家产品同方向，反而把「本 kit 为什么不省 reflector」
   这件事衬托得更立得住。

> [!NOTE]
> 2026-06-19 一个值得关注的外部信号：Agent Infra / 运行时记忆层同日在中（fastclaw/Workbuddy）、英
> （Perplexity Brain、HN 一批 agent 框架/沙箱）两个阵营冒头，且 Product Hunt 当日 6+ 个「AI 员工 /
> 主动型 AI」新品落地——「记忆层」正从概念变赛道。本 kit 的坐标价值正在于：当人人都喊 agent memory 时，
> 用四角色把「在解哪道题」拆清楚，比追新产品更重要。

## 一条最小闭环（不依赖任何外部知识库）

```
Doer 跑 → critic(你的质检器) 吐 Verdict
       → librarian.LocalMarkdownAdapter 写 memory/store/*.md
       → retrieval.memory_search 索引 + 检索
       → 下次 Doer 开场注入 top-k
       → 若 issue 累计超阈值 → evolve.prepare 跑 eval → 涨分才改 Doer prompt
```

`reflector` 接你已有的质检器，`librarian` 用内置 LocalMarkdownAdapter，`retrieval`/`evolve` 开箱即用。

## 完整调用链路：热环 / 冷环 / 人的锚点

闭环的本质是**两个回路 + 一个共享 Store**：线上实时的「热环」全自动、人不介入；离线批处理的「冷环」机器自动跑，但尺子和校准靠人。人不在热环里，人锚在冷环的几个关键节点上。

```
═══════════════ 热环（线上 · 实时 · 全自动 · 人不介入）═══════════════

① Doer 要回复用户了（你的产品 agent）                       【自动 · 线上】
      │  触发：每次任务 / 每轮对话
      ▼
② 检索注入（开场前的前置动作）                              【自动】
      │  retrieval/memory_search.py
      │  query = 当前场景词
      │  ↓ FTS5(trigram) 全文 + LIKE 短词兜底
      │  ↓ RRF 融合 + 时间衰减(半衰期)
      │  → top-k 条历史教训 → 拼进 Doer 的 system prompt
      ▼
③ Doer 带着记忆回复用户                                     【自动 · 线上】
      │  产出：一条 trace {role, text, turn}
      ▼
   trace 落库 ── 热环到此结束，交给冷环 ──────────────────┐
                                                          │
═══════════════ 冷环（离线 · 批处理 · 机器自动，尺子/校准靠人）══│══════

④ Reflector · critic 评估                   【自动跑，⚠️ 尺子人定】│
      │  你的质检器(实现 Evaluator 协议) 读 trace、用 rubric 打分 ◄┘
      │  → Verdict {score, issues[], one_line}
      │  ⚠️ 「判得准不准」取决于：
      │     · rubric 维度 = 👤 人定义（招聘 5 维 / 客服解决率…）
      │     · judge 本身可信吗 = 👤 人校准过（一致率 > 0.90）
      ▼
⑤ Reflector · librarian 沉淀                                【自动】
      │  librarian.LocalMarkdownAdapter → memory/store/*.md
      │  frontmatter: title/summary/type/tags/updated
      ▼
⑥ Store（持久记忆层）                                       【自动】
      │  memory/store/*.md
      ├─────────────► 回流到 ②：下次 Doer 开场就能检索到它
      │               （冷环产物喂回热环，闭环成立）
      │
      ▼  当某类 issue 反复出现、累积到阈值
⑦ Evolve（两条进化支路）
   ├─ 支路A · 进化「被评对象」= agent 的 prompt   【自动产建议 → 人把关】
   │    读 Store 高频 issue + 当前 prompt
   │    → LLM 产出具体改写建议
   │    → 👤 人 review 建议、决定改不改生产 prompt
   │    → 改了就回到 ①，Doer 整体变好
   │
   └─ 支路B · 进化「评估器」= judge 这把尺子      【自动跑分，前置靠人】
        evolve/prepare.py 范式：改 judge → 跑 eval → 涨分 keep、held_out 不漂移
        ⚠️ 前置必须先有 👤 人标的 ground truth labels，
           否则进化在拟合噪声 = 越跑越歪
```

### 生效分三档（不是一启动就全自动）

```
第 0 档（只有热环）：Doer 检索注入历史教训
   生效条件：Store 已有教训 → 立刻自动转，无需人
   （但 Store 怎么来的？得先有人定义 rubric、跑过冷环）

第 1 档（热环 + 冷环前半）：评估 → 沉淀 → 检索回流
   生效条件：① 人定义 rubric 维度  ② 人校准 judge 到可信(>0.90)
   满足后 ④⑤⑥ 自动批处理，教训自动回流热环

第 2 档（全闭环 + 进化）：agent 和尺子都自我改进
   支路A 生效：自动产建议，但「改生产」这一刀必须人来切
   支路B 生效：必须先有人标的 ground truth labels + 足够真实样本
```

### 人的 4 个不可替代锚点

机器负责**搬运和计算**（检索、打分、沉淀、产建议、跑分）；人锚在 4 个机器替不了的地方：

| 锚点 | 人做什么 | 为什么 agent 替不了 |
|---|---|---|
| **定义尺子** | 写 judge rubric 的维度 | 评估维度是业务价值判断，因领域而异，没有通用解 |
| **校准尺子** | 标 ground truth labels、验 judge 一致率 | **唯一绝对替不了的**——judge 拿什么当「对」的基准？只能是人标的真值。缺它，闭环在自我循环里拟合噪声 |
| **把关改进** | review 改写建议、决定是否改生产 | 改动直接作用于线上 agent，不可逆，要人担责 |
| **喂真实信号** | 攒真实样本扩 golden set | agent 造不出真实用户行为；样本代表性决定结论是否成立 |

> **一句话**：机器让闭环转得快，人让闭环不转歪。
>
> 这个架构里 agent 越自动，人越要守住「校准尺子」这个锚——一旦尺子歪了，机器会**用全速把 agent 优化到错误方向**。所以「宁可不进化，也不让它拟合噪声」是纪律，不是保守。
