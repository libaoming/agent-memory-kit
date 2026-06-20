> 🌏 **English** | [中文](methodology.zh-CN.md)

# Methodology: the four roles of runtime agent memory

## Starting point: Anthropic's "a second set of agents does the remembering"

A counterintuitive engineering stance: **don't let the agent take notes / reflect while it's working**. Four reasons:

1. **Context pollution**: the Doer's context is already stuffed with the task; piling reflection on top steals tokens and dilutes attention.
2. **Self-justification bias**: an agent judging itself right after making a decision naturally tends to say "correct."
3. **Timing mismatch**: doing the work must be fast and real-time; review can be slow, offline, and run on a cheaper model.
4. **Uncontrolled writes**: long-term memory is an asset; it needs an independent gate, and the executor must not casually rewrite its own constitution.

So you split it into **Doer (stateless execution) + a second set of agents (evaluate/distill) + a persistent memory layer**. This is not a new invention; it's the engineering version of the actor-critic / generator-evaluator architecture applied to agent memory (academically corresponding to Reflexion, and the "memory stream + reflection" of Generative Agents).

## The four roles

```
Doer → trace → Reflector(critic + librarian) → Store → retrieve & inject back into Doer
```

- **Doer**: stateless, a fresh ephemeral context each round, only responsible for completing the task.
- **Trace**: a complete trajectory with turn ordering (readable, replayable).
- **Reflector**: a second set of agents in an isolated context, with two jobs —
  - *critic*: evaluate how this round went and where it erred (a structured score + issues, not free text).
  - *librarian*: distill which parts are worth committing as lasting lessons.
- **Store**: a structured persistence layer; writes go through a gate (quota / dedup / calibration).
- **Retrieve & inject**: next time the Doer starts, retrieve the top-k relevant to the current task and inject them — not a full dump.

Three critical points: the trace must be complete and readable, the evaluation must be structured, and the Doer and Reflector must be in isolated contexts (even different models).

## Two layers of memory, don't conflate them

| | Whose memory | Tool ownership |
|---|---|---|
| **Runtime memory** | the product agent you build | this kit |
| **Dev-time memory** | Claude Code cross-session dev collaboration | harness-kit's STATUS.md / personal memory |

This kit only handles runtime memory. Don't rebuild dev-time memory here.

## This kit is abstracted from four real implementations

| Role | Source implementation | Generality | State in this kit |
|---|---|---|---|
| Retrieve & inject | `recall/wiki_search.py` | 90% | ✅ retrieval/ (paths/fields/output format parameterized) |
| Closed-loop optimize | `claude-sdk-playground/autoevolve` | 95% | ✅ evolve/ (load_skill changed to dependency injection) |
| critic evaluation | a quality grader | medium | 🟡 reflector/ (interface stub; the grader is the first instance) |
| librarian persistence | `wiki-autoupdate.sh` | medium | 🟡 librarian/ (interface + minimal LocalMarkdown impl; Obsidian still to be abstracted) |

Why only two parts are abstracted into ready-made components: the evaluation dimensions (e.g. a 5-dimension rubric vs. a support resolution rate) and the persistence-layer schema (Obsidian vs. Notion) are business/system specific, and force-generalizing them would produce "an abstraction layer nobody can use." So these two only pin down the interface contract and are filled in by the business side — this is deliberate restraint, not unfinished work.

## Lateral comparison: which problem external agent-memory products are actually solving

"Agent memory" is an overloaded label; products under that name are in fact solving completely different problems. Decompose them along this kit's four-role coordinate system and the differences become immediately clear (the three examples below were collected 2026-06-18~19 from Hacker News / X):

| Product | What its "memory" is | Which role of this kit it hits | Form |
|---|---|---|---|
| **Parcle** (parcle.ai) | **business data** across 70+ systems, indexed and then retrieved on demand in small slices | almost entirely **retrieval** (fully automatic machine, no reflector / human review) | closed source / enterprise sales; self-reported token −70%, agent 2x, 97% accuracy |
| **Draft** (github.com/idodekerobo/draft, MIT) | a team's **product decisions / context** (gathered from Slack/Granola/GitHub/sessions) | **Capture→Review→Sync→Inject** ≈ Doer trace → **HITL-style reflector** → librarian(git) → injection | open source / local-first; multi-agent (CC/Codex/Cursor/Hermes) |
| **Perplexity Brain in Computer** (released 2026-06-19) | a "context graph" deposited from **continuous cross-session learning**, building state for Computer so it gets more stateful the more it runs | **retrieval (graph retrieval) + implicit librarian (auto-accumulating state)**, still **no explicit reflector / human review** | closed source / Perplexity Max research preview |

Three things this validates about this kit's design:

1. **Parcle proves that "pure retrieval" can also become a product**, but it has no reflector / evolve cold loop — memory only goes in and is never "reflected on and distilled," relying on the data itself being structured enough (an enterprise data warehouse). This kit targets **unstructured experience and lessons** (the pits you fell into), so the reflector cannot be skipped — that is precisely where the two diverge.
2. **Draft's Review step = a HITL-style reflector**: the machine-distilled context update first lands in an inbox and waits for a human nod before entering the store. This kit's `reflector` is currently automatic evaluation and distillation; if you want to add the tier of "important memories only land in the store after human confirmation," Draft's inbox + a separate cloned git for syncing is an engineering pattern you can copy directly (echoing the "4 irreplaceable human anchors" below).
3. **Perplexity Brain and Parcle belong to the same camp of "fully automatic accumulation + pure retrieval / graph,"** confirming once again: most agent-memory products that can currently run as commercial products have cut out the reflector cold loop — they bet that **the data / interaction signal itself is structured enough** (enterprise warehouse, computer-use operation traces, knowledge graph), winning on volume rather than doing "reflection and distillation." This kit's divergence is therefore clearer: when targeting **unstructured experience and lessons** (the pits you fell into, the boundaries you misjudged), without the critic-evaluation step, memory only grows noisier and retrieval recall only gets dirtier — the reflector is not optional but the critical point. Three products pointing the same way actually makes the case for "why this kit does not skip the reflector" stand up even more firmly.

> [!NOTE]
> A notable external signal on 2026-06-19: the Agent Infra / runtime-memory-layer space surfaced on the same day in both the Chinese (fastclaw / Workbuddy) and English (Perplexity Brain, a batch of agent frameworks / sandboxes on HN) camps, and Product Hunt that day had 6+ "AI employee / proactive AI" new products landing — the "memory layer" is turning from a concept into a competitive track. This kit's coordinate value lies exactly here: when everyone is shouting agent memory, using the four roles to dissect "which problem is it actually solving" matters more than chasing new products.

## A minimal closed loop (depending on no external knowledge base)

```
Doer runs → critic (your quality checker) emits a Verdict
          → librarian.LocalMarkdownAdapter writes memory/store/*.md
          → retrieval.memory_search indexes + retrieves
          → next Doer opening injects top-k
          → if accumulated issues exceed the threshold → evolve.prepare runs eval → only raise score → change Doer prompt
```

`reflector` plugs into your existing quality checker, `librarian` uses the built-in LocalMarkdownAdapter, and `retrieval` / `evolve` work out of the box.

## Full call chain: hot loop / cold loop / human anchors

The essence of the closed loop is **two loops + one shared Store**: the online real-time "hot loop" is fully automatic with no human in it; the offline batch "cold loop" runs automatically on the machine, but its yardstick and calibration depend on humans. The human is not in the hot loop; the human is anchored at a few key nodes of the cold loop.

```
═══════════════ HOT LOOP (online · real-time · fully automatic · no human) ═══════════════

① Doer is about to reply to the user (your product agent)        [auto · online]
      │  trigger: every task / every conversation turn
      ▼
② Retrieve & inject (a pre-action before the opening)            [auto]
      │  retrieval/memory_search.py
      │  query = current scenario terms
      │  ↓ FTS5(trigram) full-text + LIKE short-word fallback
      │  ↓ RRF fusion + time decay (half-life)
      │  → top-k historical lessons → spliced into the Doer's system prompt
      ▼
③ Doer replies to the user carrying the memory                   [auto · online]
      │  output: one trace {role, text, turn}
      ▼
   trace persisted ── hot loop ends here, handed to the cold loop ──────────┐
                                                                            │
═══════════════ COLD LOOP (offline · batch · auto machine, yardstick/calibration by humans) ══│══

④ Reflector · critic evaluation              [auto run, ⚠️ yardstick set by human] │
      │  your quality checker (implements the Evaluator protocol) reads the trace, scores via rubric ◄┘
      │  → Verdict {score, issues[], one_line}
      │  ⚠️ "how accurate the judgment is" depends on:
      │     · the rubric dimensions = 👤 human-defined (a 5-dim rubric / support resolution rate…)
      │     · is the judge itself trustworthy = 👤 human-calibrated (agreement rate > 0.90)
      ▼
⑤ Reflector · librarian deposit                                  [auto]
      │  librarian.LocalMarkdownAdapter → memory/store/*.md
      │  frontmatter: title/summary/type/tags/updated
      ▼
⑥ Store (persistent memory layer)                                [auto]
      │  memory/store/*.md
      ├─────────────► flows back to ②: next Doer opening can retrieve it
      │               (cold-loop output feeds back to the hot loop, closing the loop)
      │
      ▼  when a class of issue recurs and accumulates to the threshold
⑦ Evolve (two evolution branches)
   ├─ branch A · evolve the "evaluated object" = the agent's prompt  [auto suggests → human gates]
   │    reads high-frequency issues in the Store + the current prompt
   │    → LLM produces concrete rewrite suggestions
   │    → 👤 human reviews the suggestions, decides whether to change the production prompt
   │    → once changed, back to ①, the Doer gets better overall
   │
   └─ branch B · evolve the "evaluator" = the judge, that yardstick  [auto scoring, prerequisites by human]
        evolve/prepare.py paradigm: change judge → run eval → keep if score rises, held_out must not drift
        ⚠️ the prerequisite is that there must first be 👤 human-labeled ground-truth labels,
           otherwise evolution is fitting noise = drifting further off the more it runs
```

### Activation in three tiers (it is not fully automatic the moment you start)

```
Tier 0 (hot loop only): the Doer retrieves and injects historical lessons
   activation condition: the Store already has lessons → it runs automatically at once, no human needed
   (but where did the Store come from? a human must first define the rubric and run the cold loop)

Tier 1 (hot loop + first half of the cold loop): evaluate → deposit → retrieval feedback
   activation conditions: ① human defines the rubric dimensions  ② human calibrates the judge to trustworthy (>0.90)
   once met, ④⑤⑥ batch automatically, and lessons flow back into the hot loop automatically

Tier 2 (full closed loop + evolution): both the agent and the yardstick self-improve
   branch A activation: auto suggestions, but the cut of "change production" must be made by a human
   branch B activation: there must first be human-labeled ground-truth labels + enough real samples
```

### The 4 irreplaceable human anchors

The machine is responsible for **moving and computing** (retrieving, scoring, depositing, producing suggestions, running scores); the human is anchored at 4 places the machine cannot replace:

| Anchor | What the human does | Why the agent can't replace it |
|---|---|---|
| **Define the yardstick** | write the dimensions of the judge rubric | evaluation dimensions are business value judgments, varying by domain, with no universal solution |
| **Calibrate the yardstick** | label ground-truth labels, verify the judge's agreement rate | **the one absolutely irreplaceable thing** — what does the judge take as the "correct" baseline? Only human-labeled ground truth. Without it, the closed loop fits noise inside its own self-referential cycle |
| **Gate improvements** | review rewrite suggestions, decide whether to change production | the change acts directly on the live agent, is irreversible, and a human must own the accountability |
| **Feed real signal** | accumulate real samples to expand the golden set | the agent can't fabricate real user behavior; the representativeness of samples decides whether the conclusion holds |

> **In one line**: the machine makes the loop spin fast; the human keeps the loop from spinning off course.
>
> In this architecture, the more automatic the agent becomes, the more the human must hold the "calibrate the yardstick" anchor — once the yardstick bends, the machine will **optimize the agent toward the wrong direction at full speed**. So "rather not evolve than let it fit noise" is discipline, not conservatism.
