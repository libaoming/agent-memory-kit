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

## 已验证的重型实例：wiki-autoupdate

`~/.claude/scripts/wiki-autoupdate.sh` 是 librarian 的一个成熟实例（升格 chat/memory 进 Obsidian Vault）。
P2 的工作 = 把它的「采样 → 提炼 → 写持久层」抽成 `ObsidianAdapter`，与本接口对齐。
