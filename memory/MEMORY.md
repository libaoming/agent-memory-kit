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
- **steering·「记什么」声明**：__________（写给 Reflector/librarian 的入库标准：记什么、不记什么。
  MCP 挂载时填 config 的 `steering` 字段，会自动注入 `memory_write` 工具描述，写入前模型就能看到）
- **store 读写标志**：org=只读（改动走人工评审），task=读写；对外 MCP 挂载若整体只读，
  config 置 `"read_only": true`（server 不暴露 `memory_write`）
- **闭环优化**：issue 累计到阈值 → `memory/evolve/prepare.py` 跑 eval → 涨分才改 Doer prompt

## Store 分层 scope（目录即 scope，2026-07-21 起）

对齐 Anthropic Managed Agents memory 的分层 scope 设计（org 只读 + 任务级读写）：

```
memory/store/
├── org/     ← 稳定层：红线/规则/长期有效教训。低频更新，Doer 与 Reflector 只读；
│              改动走人工评审（等价官方 org-wide read-only store）
├── task/    ← 任务层：Reflector 日常写入的场景教训。可自由读写、可被 evolve 重整
└── *.md     ← 未分层散置条目（scope=default，向后兼容，检索行为不变）
```

- 检索按需过滤：`memory_search "<query>" --scope org`（多值 `--scope org,task`）；不传 = 全量。
- 注入建议：Doer 开场注入 = org 全量小集 + task 按 query top-k——红线永远在场，经验按需进场。
- **单写入者纪律**：本 kit 不做乐观并发控制——写入必须过 Reflector 单闸门，天然串行。
  何时再考虑 OCC：出现多个 Reflector 并行写同一 store 时（git 冲突检测即穷人版 OCC）。

## 写入纪律（版本 + 归因，Reflector/librarian 必守）

对齐官方「版本控制 + diff + 写归因」审计线，git 白捡全套，只需两条纪律：

1. **provenance 必填**：每条写入 store 的记忆，frontmatter 的 `provenance` 必须填触发它的
   trace/session 标识（如 `trace-0712-batch` / `call_records#1234`）。没有出处的教训不入库——
   回答「这条记忆哪来的」是审计线的最低要求。
2. **单条 commit 归因**：每次 Reflector 写入/修改 store 单独 `git commit`，message 格式
   `memory(<scope>): <一句话> [src: <trace标识>]`。版本历史 = `git log`，版本 diff = `git diff`，
   归因 = commit + provenance 双线。禁止把多条记忆改动混进一个 commit。

## 启动协议（写进本项目 CLAUDE.md 的 L1）

- Doer 每次运行前，检索注入走**两段式**（对齐官方 memory「先读目录、再读条目」，省 context）：
  1. **先读 index**：`memory_search "<场景词>" --top 8` → 只回 title/summary/path 轻量索引行
  2. **后读正文**：对真正相关的 2-3 条再取全文注入——CLI 加 `--full`（MCP 传 `full: true`），
     文件型 Doer 也可直接按 path 读 store 原文
- 红线走 `--scope org`，经验走 `--scope task`；**别第一段就 `--full` 全量灌**。
- 一轮运行结束：trace → Reflector 评估/提炼 → 写 `memory/store/task/`（守上面两条写入纪律）。
- 别让 Doer 直接写长期记忆——写入必须过 Reflector 这道闸门。

## P0 现状（本 kit MVP）

- ✅ `retrieval/` 检索注入：可用（FTS5 + 时间衰减 + RRF + scope 分层过滤 `--scope`）。
- ✅ `evolve/` 闭环优化：可用（fixture → agent → judge → TSV 记账）。
- 🟡 `reflector/` critic 评估：**接口占位**，接你自己的质检器（见该目录 README）。
- 🟡 `librarian/` 持久层适配：**接口占位**，接你的知识库后端（见该目录 README）。
