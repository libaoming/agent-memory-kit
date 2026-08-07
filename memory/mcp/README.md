# mcp/ — 把 memory-kit 暴露成 MCP server ✅ ready

把 kit 的「检索注入」+「持久化」两段，通过 **MCP（Model Context Protocol）** 暴露给任何
MCP 客户端（Claude Code / Claude Desktop / Cursor / 你自建 agent）。这样记忆层不再绑定单个
项目——凡支持 MCP 的 agent 都能挂上同一套运行时记忆。

> **零依赖**：`server.py` 只用 Python 标准库实现 stdio + newline-delimited JSON-RPC 2.0，
> 沿用本 kit 「retrieval/evolve 纯标准库」的哲学——装完 kit 即可挂载，**无需 `pip install mcp`**。

## 暴露的 tools

| tool | 作用 |
|---|---|
| `memory_search(query, top=8, full=false)` | 按当前任务检索 top-k 相关记忆（当前视图 + `confidence` + `provenance`）。**两段式**：默认只回轻量 index 行（title/summary/path）；对真正相关的少量条目再传 `full=true` 取正文全文。|
| `memory_write(title, content, summary, …)` | 落盘一条记忆；同名再写自动**版本化**归档旧 claim。可带 `provenance`/`confidence`/`change_reason`/`contradiction`，写后自动重建索引。config 有 `steering` 时其「记什么」声明自动注入本工具描述；`read_only: true` 时本工具不暴露。|

## 在客户端注册（stdio）

Claude Code：`claude mcp add memory -- python3 /abs/path/agent-memory-kit/memory/mcp/server.py --config /abs/path/config.json`

或手写 MCP 客户端配置（Claude Desktop / Cursor 等）：

```json
{
  "mcpServers": {
    "memory": {
      "command": "python3",
      "args": [
        "/abs/path/agent-memory-kit/memory/mcp/server.py",
        "--config", "/abs/path/config.json"
      ]
    }
  }
}
```

`--config` 复用 `retrieval/` 的 config（`store_dir` / `db_path` / `frontmatter_fields` /
`conf_penalty` …），见 [`../retrieval/config.example.json`](../retrieval/config.example.json)。
缺省则用内置默认（指向 Obsidian vault）。

挂载接口另有两个槽位（对齐官方 memory 的 steering prompt + read-only store 设计）：

- `steering`：「记什么/不记什么」声明。非空时自动前置进 `memory_write` 的工具描述，
  挂载的 agent 在写入前就能看到入库标准——不用改客户端 prompt。
- `read_only`：`true` = 只读挂载。`tools/list` 不再暴露 `memory_write`，硬调用也会被拒。
  适合把同一个 store 以只读方式挂给多个消费端、写入只走 Reflector 单闸门的拓扑。

## 自测（不装任何客户端）

用纯标准库喂一串 JSON-RPC 走一遍握手：

```bash
printf '%s\n' \
  '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}' \
  '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' \
  '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"memory_search","arguments":{"query":"班次 夜班"}}}' \
  | python3 server.py --config /abs/path/config.json
```

应看到 3 行 JSON-RPC 响应：initialize 握手、两个 tool 的清单、检索结果。
