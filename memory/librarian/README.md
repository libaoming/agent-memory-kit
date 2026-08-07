# librarian/ — 持久层适配器接口（P2 占位）

记忆四角色里 Reflector 的「提炼」一半 + Store 的写入：把 Reflector 评估出的 issue / 教训，
提炼成结构化的长期记忆，写进某个持久后端，供 `retrieval/` 检索。

## 为什么是占位

持久后端各家不同（本地 Markdown / Obsidian / Notion / Roam / 数据库），schema 也不同。
本 kit 只定义**适配器接口**，具体后端由业务方实现。最简单的实现就是「写本地 `memory/store/*.md`」，
`retrieval/memory_search.py` 开箱即能索引。

## 接口契约（`adapter.py`）

```python
class PersistenceAdapter(Protocol):
    def write_page(self, title, content, metadata: dict) -> str: ...  # 返回写入路径
    def update_index(self) -> None: ...
    def commit(self, message: str) -> None: ...
```

## 内置最简实现：LocalMarkdownAdapter

写 `memory/store/<slug>.md`，带 `retrieval` 期望的 frontmatter（title/summary/type/tags/updated）。
这是默认路径——配合 `retrieval` 就是一条能跑的最小记忆闭环，无需任何外部知识库。

可选两字段（Reflector 给出时才写，不给则完全不影响旧行为）：
- `provenance`：这条记忆的出处（来源事件/原文/发话人/URL）。检索时随结果带出，让 agent 引用记忆能标来源。
- `confidence`：置信度 `0-1`（也接受 `90` 这类百分数）。检索按它温和降权——低置信记忆排名下沉、可要求复核，高置信≈不降。降权幅度由 config 的 `conf_penalty`（默认 0.5，即最多打对折）控制；无此字段的记忆视为满置信、排序不变。

### 版本化 claim（更新≠覆盖）

同一条记忆（同 `title`）被再次 `write_page` 且内容有实质变化时，**不覆盖旧 claim**：旧的
summary/updated/confidence 归档进正文的「## 历史 claim」段、frontmatter 记 `version` 与
`supersedes`。当前 frontmatter/正文永远是最新视图（检索只看它），旧态留在正文可 diff。
borrow 自 N71 的 bitemporal claim——「事实变了」与「事实错了」都留痕，不静默丢失。

`write_page` 的 `metadata` 可选：
- `change_reason`：本次变更原因，写进历史条目。
- `contradiction: true`：新 claim 与旧结论矛盾时标记 frontmatter，供人/agent 裁决。

内容无变化时幂等（不增版本、不重复历史）。新增的 `version/supersedes/contradiction` 不在
`frontmatter_fields` 索引映射里，检索端读到当前视图即可，不受干扰。

## 写入闸门一：不可信出处改写（borrow 自 qm）

上面的 `provenance` 字段有个前提没说破：**它是写入者自己填的**。当写入者就是模型时，
这个字段不构成任何保证——模型可以填一个它凭空想象的出处，检索端却会把它当作已核实的来源带出去。

`yc-software/qm` 的 `foldCapture`（`src/memory/memory-service.ts:59-64`）给出的解法是
**在数据结构层面区分「系统盖的章」和「模型说它盖了章」**：系统写入时统一加权威前缀，
而模型自己产出的同形态标记，一律改写降级：

```
模型写的 "(2026-08-01) 某事"     → 改写成 "on 2026-08-01: 某事"      # 从日期戳降级成普通文字
模型写的 "某事 (said in 频道A)"  → 改写成 "某事 [claimed source: 频道A]"  # 从来源降级成「声称的来源」
```

只有系统自己的可信路径（qm 里是 `cc:` 抄送）才 `trustedProvenance=true`，标记原样保留。

落到本 kit 的建议实现：`write_page` 应把 `metadata["provenance"]` 分成两档存——
系统采集链路填的记为已核实，模型在 content 里自述的一律带上「声称」前缀，**永不合并成同一个字段**。
检索端据此可以只信前者。这一条与 `confidence` 正交：confidence 说的是「这条记忆多可能是对的」，
provenance 档位说的是「谁在担保它的来源」，**低置信 ≠ 出处存疑，两者要分别表达**。

## 写入闸门二：冲突决策四元组（borrow 自 TDB batchDedup）

qm 那道闸管「出处可不可信」，这道管「和已有记忆什么关系」。新记忆落盘前先撞一次旧记忆
（向量/全文召回 top-5 相似候选），由 LLM 对每个候选判定四元组：

```
{action: store | update | merge | skip, target: <候选 title>}
  store  = 都不是同一件事 → 新建
  update = 同一件事的新结论 → 写进旧 title（版本化归档旧 claim）
  merge  = 与旧条互补 → 写进旧 title，正文为融合后内容，change_reason 注明 merge 来源
  skip   = 已被旧条覆盖 → 不写
```

没有这道闸的后果：同一条教训以五种措辞存五份，检索时互相稀释排名，且更新时只改到其中一份。
TDB 的实现（MemoryCore `record/l1-dedup.ts`）里 merge 还会给目标记录追加 timestamps 轨迹、
version+1——本 kit 的版本化 claim 恰好承接这个语义（update/merge 都走 `write_page` 同名再写）。

**kit 内落地**：MCP server 的 `memory_write` 已内置此闸（`dedup_gate`，默认开）——新 title
首写若命中相似旧记忆，先返回候选清单让模型判定，判定 store 才放行（`dedup_checked=true`）；
同名再写本来就是 update/merge 语义，不重复过闸。**「同名」判据 = `find_by_title` 按
frontmatter title 全树精确比对**（含 org//task/ scope 子目录，版本化写回原位置）——
不是 path 存在性：slug 会把不同 title 折叠到同一文件名，path 冒充 title 会误并无关记忆
（真撞上 slug 碰撞时新条目自动加序号后缀落盘）。闸门召回对 title+summary 做 3 字 shingle
切分，未分词的整句中文摘要也能命中候选。直连 `adapter.write_page` 的重型后端，
应在自己的写入链路里复刻同样的「先撞后写」。

## 写入闸门三：先分类、再打分（borrow 自 TDB skill 双闸）

前两道闸管出处和冲突，这道管「这条内容配不配入库」。TDB 的 skill 写入闸
（`skill/prompts/skill-review-prompt.ts`）把「宁缺毋滥」做成了两道可执行的数值 gate，搬给 librarian：

**闸 A · 分类闸**：候选先五选一——教训(lesson) / 长期事实(fact) / 可复用工作流(skill) /
临时上下文 / 噪音。**只有前两类可写本 store**；工作流该去 skills 库，后两类丢弃。
防的事：模型把「这次对话里碰巧的操作步骤」当资产存下来。

**闸 B · 四维打分**（每维 0-25，总分 ≥72 且任一维 ≥12 才落库）：

| 维度 | 问的问题 |
|---|---|
| 独立完整 | 跳出这段对话还成立吗？不看 trace 能懂吗？ |
| 行为增量 | 下次同类场景，它会真的改变 Doer 的动作吗？ |
| 复用面 | 是一类场景的规律，还是只发生过一次的偶然？ |
| 边界清晰 | 说清了适用条件和反例吗？会被过度泛化吗？ |

**kit 内落地**：本 kit 不内置 LLM，这道闸跑在写入方的 prompt 里——把它写进 MCP config 的
`steering` 字段（自动注入 `memory_write` 工具描述，写入前模型必看），
`retrieval/config.example.json` 的 steering 已含可直接抄的版本。

## 整理：只在记忆有界时做，且只输出动作（borrow 自 qm）

本 kit 默认走「无界 store + 读取侧 top-k 检索」。若你的记忆是**有界**的（如「关于某个人的长期事实」
而非「踩过的坑」），另一条路是在写入侧压缩：硬顶条数 + 定期整理，然后整段注入、不做检索。
qm 走的就是这条（notebook 硬顶 300 条，每积累 10 条触发一次整理）。两条路的取舍见
`docs/methodology.zh-CN.md` 横向对照节第 4 点。

真要做整理，有两条实现纪律必须跟上：

**1. 让 LLM 输出结构化动作，不要让它重写全文。**

```
UPDATE <n>: <修订后的事实>
DELETE <n>
ADD: <新事实>
```

代码确定性地 apply 这些动作。让 LLM 重写整个记忆文件会静默丢东西——丢了你也不知道丢了什么；
动作式不会，每一次增删改都可数、可审计、可回放。配套的硬约束：优先 UPDATE 而非 DELETE+ADD；
保持每条事实原子化；**绝不删除或弱化用户明确要求记住的条目**；**永不合并两条来源不同的事实**
（这是跨 scope 污染防护）；拿不准就别动。

**2. 整理完必须回读校验，写不回去就降级。**

qm 在整理后重新读一遍，若写回的内容与预期不一致，就把该 scope 永久标记 `degraded`、
禁用整理、退回 capture-only 并打日志（`consolidation.ts:151-155`）。

这条值得单独强调：**整理是唯一会「删」记忆的环节，也就是唯一能造成不可逆数据损失的环节。**
一个「以为写成功了、其实没写进去」的整理器，会让记忆停在某个旧快照上而没有任何人发现。
后端不支持重写（只支持 append）是常见情况，**必须靠回读发现，不能靠假设**。

## 已验证的重型实例：wiki-autoupdate

`~/.claude/scripts/wiki-autoupdate.sh` 是 librarian 的一个成熟实例（升格 chat/memory 进 Obsidian Vault）。
P2 的工作 = 把它的「采样 → 提炼 → 写持久层」抽成 `ObsidianAdapter`，与本接口对齐。
