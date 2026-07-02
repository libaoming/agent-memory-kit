# mcp/ — 把 memory-kit 暴露成 MCP server ✅ ready

把 kit 的「检索注入」+「持久化」两段，通过 **MCP（Model Context Protocol）** 暴露给任何
MCP 客户端（Claude Code / Claude Desktop / Cursor / 你自建 agent）。这样记忆层不再绑定单个
项目——凡支持 MCP 的 agent 都能挂上同一套运行时记忆。

> **零依赖**：`server.py` 只用 Python 标准库实现 stdio + newline-delimited JSON-RPC 2.0，
> 沿用本 kit 「retrieval/evolve 纯标准库」的哲学——装完 kit 即可挂载，**无需 `pip install mcp`**。

## 暴露的 tools

| tool | 作用 |
|---|---|
| `memory_search(query, top=8)` | 按当前任务检索 top-k 相关记忆（当前视图 + `confidence` + `provenance`）。Doer 启动前注入相关历史教训。|
| `memory_write(title, content, summary, …)` | 落盘一条记忆；同名再写自动**版本化**归档旧 claim。可带 `provenance`/`confidence`/`change_reason`/`contradiction`，写后自动重建索引。|

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
