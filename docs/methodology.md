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

## 一条最小闭环（不依赖任何外部知识库）

```
Doer 跑 → critic(你的质检器) 吐 Verdict
       → librarian.LocalMarkdownAdapter 写 memory/store/*.md
       → retrieval.memory_search 索引 + 检索
       → 下次 Doer 开场注入 top-k
       → 若 issue 累计超阈值 → evolve.prepare 跑 eval → 涨分才改 Doer prompt
```

`reflector` 接你已有的质检器，`librarian` 用内置 LocalMarkdownAdapter，`retrieval`/`evolve` 开箱即用。
