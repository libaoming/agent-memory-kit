# MEMORY.md — {{PROJECT}} 的记忆层纪律

> 本文件由 `agent-memory-kit` 生成。它**不是记忆本身**，是「这个项目的记忆层怎么运作」的纪律文档。
> 负责人 {{OWNER}} · 初始化 {{DATE}}。

## 两层记忆，别混

这个项目可能涉及**两种不同的记忆**，分清楚才不会重复造：

| | 谁的记忆 | 记什么 | 存哪 |
|---|---|---|---|
| **运行时记忆** | 你 build 的产品 agent | 它跑出来的经验/教训（哪类对话最常翻车） | 本项目 `memory/store/`（本 kit 管这块） |
| **开发时记忆** | Claude Code（开发协作） | 这项目做到哪、有什么坑 | `STATUS.md` / `~/.claude` 个人 memory（harness-kit 管，不在这重复） |

下面只讲**运行时记忆**——本 kit 的主战场。

## 记忆四角色（运行时记忆的闭环）

```
Doer（你的产品 agent · 无状态执行）
   │ 留下 trace（每次运行的完整轨迹）
   ▼
Reflector（第二组 agent · 独立 context）
   ├─ critic   : 评估这轮干得怎样、哪里错        → memory/reflector/（接你的质检器）
   └─ librarian: 提炼哪些值得沉淀成长期教训      → memory/librarian/（接你的持久层）
   │
   ▼
Store（持久记忆 · 结构化 *.md）                  → memory/store/
   │
   ▼
检索注入回 Doer（按当前任务捞 top-k）            → memory/retrieval/memory_search.py
```

> 原理：Doer 自己边干边记会污染上下文、且有自我合理化偏差。把评估/提炼交给独立的第二组
> agent，更客观、可异步、可用更便宜模型、写入有闸门。（对应 Anthropic「agent 靠第二组
> agent 做记忆/复盘」的工程主张。）

## 本项目的接线（开工时填）

- **Doer 是谁**：__________（如：你的电话招聘 agent）
- **trace 在哪**：__________（如：call_records / *.jsonl）
- **Reflector·critic**：__________（如：复用 miaomiao-grader 的 judge）→ 见 `memory/reflector/`
- **Store 长什么样**：`memory/store/*.md`，frontmatter 至少含 `title/summary/type/tags/updated`
- **检索注入时机**：__________（如：每通电话开场前 `memory_search "<场景词>" --top 5` 注入 prompt）
- **闭环优化**：issue 累计到阈值 → `memory/evolve/prepare.py` 跑 eval → 涨分才改 Doer prompt

## 启动协议（写进本项目 CLAUDE.md 的 L1）

- Doer 每次运行前：先 `memory_search` 拉相关历史教训注入 context（别全量灌）。
- 一轮运行结束：trace → Reflector 评估/提炼 → 写 `memory/store/`。
- 别让 Doer 直接写长期记忆——写入必须过 Reflector 这道闸门。

## P0 现状（本 kit MVP）

- ✅ `retrieval/` 检索注入：可用（FTS5 + 时间衰减 + RRF）。
- ✅ `evolve/` 闭环优化：可用（fixture → agent → judge → TSV 记账）。
- 🟡 `reflector/` critic 评估：**接口占位**，接你自己的质检器（见该目录 README）。
- 🟡 `librarian/` 持久层适配：**接口占位**，接你的知识库后端（见该目录 README）。
