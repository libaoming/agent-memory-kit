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

## 已验证的重型实例：wiki-autoupdate

`~/.claude/scripts/wiki-autoupdate.sh` 是 librarian 的一个成熟实例（升格 chat/memory 进 Obsidian Vault）。
P2 的工作 = 把它的「采样 → 提炼 → 写持久层」抽成 `ObsidianAdapter`，与本接口对齐。
