# agent-memory-kit

给「要构建带记忆的 agent」的项目，一套**运行时记忆层脚手架**。

> ⚠️ **诚实定位：这是脚手架，不是即插即用的记忆中间件。**
> 它给你骨架代码 + 注入点 + 纪律文档，让你少写 70% 的样板；但评估维度、持久层 schema
> 这些业务特定的东西仍需你填。别指望 `pip install` 就有记忆。

## 它解决什么

大多数 agent 是无状态的：每次跑完即焚，上一次踩的坑下一次照踩。给它「记忆」通常要手搓四样东西——
评估器、持久层、检索、闭环优化。本 kit 把其中**最通用的两块**抽成现成件，另两块给接口占位。

## 记忆四角色

```
Doer（你的 agent · 无状态执行）
   │ 留下 trace
   ▼
Reflector（第二组 agent · 独立 context）
   ├─ critic   : 评估哪里错      → reflector/   🟡 接口占位(P1)
   └─ librarian: 提炼成长期教训   → librarian/   🟡 接口占位(P2)
   │
   ▼
Store（持久记忆 *.md）
   │
   ▼
检索注入回 Doer                  → retrieval/    ✅ 可用(P0)
                                   evolve/       ✅ 可用(P0)
```

> 原理对应 Anthropic 的工程主张：**agent 本体不负责记忆，记忆/复盘交给第二组 agent**——
> 更客观、可异步、写入有闸门。详见 `docs/methodology.md`。

## P0 现成的两块

| 模块 | 作用 | 抽自 |
|---|---|---|
| **retrieval/** | FTS5 + 时间衰减 + RRF 的检索注入，Doer 启动前捞 top-k 历史教训 | recall/wiki_search.py |
| **evolve/** | fixture → agent → judge → TSV 记账的闭环优化，prompt 改了自动验分 | claude-sdk-playground/autoevolve |

两块都是**纯标准库 + claude CLI 订阅模式（零 API 成本）**，配置经 JSON 注入，无硬编码路径。

## 快速开始

```bash
# 1. 检索注入：把 store 配好，Doer 跑前捞历史教训
python3 memory/retrieval/memory_search.py "你的场景关键词" --config your_config.json --top 5

# 2. 闭环优化：prompt 改了跑一次，看分涨没涨
python3 memory/evolve/prepare.py --config your_amk_config.json --runs 3
```

## 和另外两个 kit 的关系

```
harness-init (skill = 编排上层)
   ├─ harness-kit              开发时记忆 · L1-L4 防御脚手架
   ├─ context-engineering-kit  CONTEXT.md · 7 层上下文审计
   └─ agent-memory-kit         运行时记忆 · 本仓库
```

三者由 `harness-init` 在建项目时按需挂载——要构建带记忆 agent 才挂本 kit，保持轻量默认。

## 真实案例

`examples/recruit-voice-runtime/` —— 以一个招聘语音 agent 为例，把一个 critic 型质检器
接进本 kit：质检评出的 issue 沉淀进 store 供检索 + 质检 rubric 喂给 evolve 当进化标尺。
自包含可独立跑，同时是 dogfood（验证抽象没把能用的脚本变成谁都不好用的抽象层）。

## License

MIT
