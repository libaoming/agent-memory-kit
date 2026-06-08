# examples/recruit-voice-runtime — dogfood：把质检器接进记忆闭环

以一个招聘语音 agent 为例，把一个 critic 型 Reflector（质检器）接进 agent-memory-kit，
验证抽出来的 retrieval / evolve 两块**真能套回真实项目**，而不是变成「谁都不好用的抽象层」。

> 本例自包含、可独立跑：自带示例 agent prompt（`prompts/recruiter.md`）与质检维度（`judge.md`）。
> 把它们换成你项目的真实 prompt / 质检器即可。

## 两条已验证的链路

### 1. retrieval：质检 issue → store → 检索注入
```
质检器评出 issue ──grader_verdict_adapter──▶ Verdict
   ──LocalMarkdownAdapter──▶ memory/store/*.md
   ──memory_search(FTS5+时间衰减+RRF)──▶ agent 开场前捞「这场景最常踩的坑」
```
跑：
```bash
python3 build_store.py                       # demo：内置泛化教训（不调 LLM）
python3 ../../memory/retrieval/memory_search.py "班次 录音 开场" \
        --config ./memory_config.json --reindex --top 5
```
✅ 实测：检索正确命中「关键槽位（班次）漏采」「录音告知」等教训。

### 2. evolve：同一套 rubric → 闭环优化 agent prompt
```
judge.md(质检维度) + agent prompt(prompts/recruiter.md) + fixture
   ──prepare.py──▶ haiku 现场回复 → sonnet 按质检维度打分 → TSV 记账
```
跑：
```bash
python3 ../../memory/evolve/prepare.py --config ./amk_config.json --runs 3
```
✅ 实测 baseline avg≈6：judge 精准抓出招聘客服常见失分点（漏问关键槽位 / 未自报身份 /
漏录音告知 / 首句没接住），证明**线上质检与离线进化共用一套标尺**——质检发现的坑直接成为进化方向。

## 关键文件
- `prompts/recruiter.md` — 自带的招聘 agent prompt（被 evolve 进化的对象）
- `build_store.py` — Reflector(质检器) → librarian → store 的接线（含接你自己质检器的 `--grade` 示例）
- `memory_config.json` / `amk_config.json` — retrieval / evolve 配置
- `judge.md` — 质检 5 维 rubric（改成 evolve 的 {score,pass,reasons} 契约）
- `eval/train_set.jsonl` — 招聘场景 fixture

## 结论
一个孤立的「打分器」质检器，接上 retrieval + evolve 后就升级成完整的记忆闭环 Reflector——
评出的 issue 沉淀进 store 供检索注入，质检维度复用为进化标尺。这是把 critic 收编进
`reflector` adapter 的最小可跑证明。
