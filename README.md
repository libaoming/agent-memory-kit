> 🌏 **English** | [中文](README.zh-CN.md)

# agent-memory-kit

A **runtime memory-layer scaffold** for projects that need to build a memory-equipped agent.

> ⚠️ **Honest framing: this is a scaffold, not a plug-and-play memory middleware.**
> It hands you skeleton code + injection points + discipline docs, saving you ~70% of the boilerplate;
> but the evaluation dimensions and the persistence-layer schema — the business-specific parts — are still
> yours to fill in. Don't expect `pip install` to give you memory.

## What it solves

Most agents are stateless: each run is fire-and-forget, and the pit you fell into last time you fall into again.
Giving an agent "memory" usually means hand-rolling four things — an evaluator, a persistence layer, retrieval,
and a closed-loop optimizer. This kit turns the **two most general ones** into ready-made parts, and leaves the
other two as interface placeholders.

## The four memory roles

```
Doer (your agent · stateless execution)
   │ leaves a trace
   ▼
Reflector (second set of agents · isolated context)
   ├─ critic    : evaluate what went wrong   → reflector/   🟡 interface stub (P1)
   └─ librarian : distill into lasting lessons → librarian/   🟡 interface stub (P2)
   │
   ▼
Store (persistent memory *.md · provenance + confidence · versioned claims)
   │
   ▼
retrieve & inject back into Doer        → retrieval/    ✅ ready (P0)
                                          evolve/       ✅ ready (P0)
   │
   └─ expose to any MCP client          → mcp/          ✅ ready (stdio, zero-dep)
```

> This mirrors Anthropic's engineering stance: **the agent itself does not own memory; memory/reflection is
> handed to a second set of agents** — more objective, asynchronous, and gated on write.
>
> 📐 For the **full call chain** (hot loop / cold loop / the 4 human anchor points in the loop) see
> [`docs/methodology.md`](docs/methodology.md#full-call-chain-hot-loop--cold-loop--human-anchors).

## The two ready-made P0 parts

| Module | Role | Distilled from |
|---|---|---|
| **retrieval/** | FTS5 + time decay + RRF retrieval-injection; before the Doer starts, fetch the top-k historical lessons. Carries per-memory **provenance** (source) + **confidence** (low-confidence memories get down-weighted) | recall/wiki_search.py |
| **evolve/** | fixture → agent → judge → TSV-ledger closed-loop optimization; when the prompt changes, auto-verify the score | claude-sdk-playground/autoevolve |
| **mcp/** | expose retrieval + write to any MCP client (Claude Code / Desktop / Cursor) over stdio; writes are **versioned claims** (updates archive the old claim, never overwrite) | — (borrows N71's bitemporal claim) |

All are **pure standard library + claude CLI subscription mode (zero API cost)**, configured via JSON injection, with no hardcoded paths.

## Quick start

```bash
# 1. Retrieval-injection: wire up the store, fetch historical lessons before the Doer runs
python3 memory/retrieval/memory_search.py "your scenario keywords" --config your_config.json --top 5

# 2. Closed-loop optimization: run once after changing the prompt, see whether the score went up
python3 memory/evolve/prepare.py --config your_amk_config.json --runs 3

# 3. Expose as an MCP server (stdio, zero-dep) so any MCP client can search/write memory
claude mcp add memory -- python3 memory/mcp/server.py --config your_config.json
```

## How it relates to the other two kits

```
harness-init (skill = orchestration layer on top)
   ├─ harness-kit              dev-time memory · L1-L4 defense scaffold
   ├─ context-engineering-kit  CONTEXT.md · 7-layer context audit
   └─ agent-memory-kit         runtime memory · this repo
```

`harness-init` mounts all three on demand when bootstrapping a project — mount this kit only when you're building
a memory-equipped agent, keeping the default lightweight.

Companion repos: **[harness-kit](https://github.com/libaoming/harness-kit)** (dev scaffold) · **[context-engineering-kit](https://github.com/libaoming/context-engineering-kit)** (context audit).

## Real-world example

`examples/recruit-voice-runtime/` — using a voice agent as the example, it wires a critic-style quality checker
into this kit: the issues the checker scores get distilled into the store for retrieval, and the checker's rubric
feeds evolve as the evolution yardstick. It is self-contained and runnable on its own, and at the same time serves
as dogfood (verifying the abstraction didn't turn working scripts into an abstraction layer nobody can use).

## License

MIT
