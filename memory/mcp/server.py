#!/usr/bin/env python3
"""server.py — 把 agent-memory-kit 暴露成 MCP server（stdio 传输，纯标准库零依赖）。

记忆四角色里的「检索注入」+「持久化」两段，通过 MCP 暴露给任何 MCP 客户端
（Claude Code / Claude Desktop / Cursor / 你自建 agent）。Doer 启动前可用
`memory_search` 拉相关历史教训注入 context；Reflector 可用 `memory_write` 把新教训
落盘（自带 provenance/confidence + 版本化 claim）。

为什么手写而非用 mcp SDK：本 kit 的卖点是零 pip 依赖（retrieval/evolve 纯标准库），
MCP server 沿用同一哲学——只用标准库实现 stdio + newline-delimited JSON-RPC 2.0，
装完 kit 即可挂载，无需 `pip install mcp`。

用法（在 MCP 客户端里注册一个 stdio server）：
    command: python3
    args: ["/abs/path/to/memory/mcp/server.py", "--config", "/abs/path/to/config.json"]
config.json 复用 retrieval 的 config（store_dir / db_path / frontmatter_fields / conf_penalty …）。

暴露的 tools：
    memory_search(query, top=8)   → 按当前任务检索 top-k 相关记忆（当前视图 + confidence + provenance）
    memory_write(title, content, summary, ...) → 落盘一条记忆；同名再写自动版本化归档旧 claim
"""
import os, sys, json, argparse

# 复用 kit 的检索后端 + 持久层适配器（兄弟目录，脚手架式动态挂载）
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "retrieval"))
sys.path.insert(0, os.path.join(_HERE, "..", "librarian"))
from memory_search import MemoryStore, load_config  # noqa: E402
from adapter import LocalMarkdownAdapter  # noqa: E402

PROTOCOL_VERSION = "2024-11-05"
SERVER_INFO = {"name": "agent-memory-kit", "version": "0.1.0"}

TOOLS = [
    {
        "name": "memory_search",
        "description": ("检索运行时记忆 store，按当前任务返回 top-k 相关历史教训（当前视图，"
                        "带 confidence 置信度与 provenance 出处）。agent 启动前用它注入相关记忆，"
                        "而非把整个 store 灌进 context。"),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "任务/场景关键词，空格分隔"},
                "top": {"type": "integer", "description": "返回条数，默认 8", "default": 8},
            },
            "required": ["query"],
        },
    },
    {
        "name": "memory_write",
        "description": ("把一条新教训落盘为记忆。同名记忆再写且内容有实质变化时自动版本化——"
                        "旧 claim 归档进历史段（非覆盖），可 diff。传 provenance 记出处、"
                        "confidence 记置信度（检索按它降权）、change_reason 记变更原因、"
                        "contradiction=true 标与旧结论矛盾。"),
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "记忆标题（同名=同一条，触发版本化）"},
                "content": {"type": "string", "description": "记忆正文（当前 claim）"},
                "summary": {"type": "string", "description": "一句话摘要（检索主要匹配它）"},
                "tags": {"type": "string", "description": "空格分隔标签"},
                "type": {"type": "string", "description": "记忆类型，默认 lesson"},
                "provenance": {"type": "string", "description": "出处：来源事件/原文/发话人/URL"},
                "confidence": {"type": "string", "description": "置信度 0-1（或百分数如 90）"},
                "change_reason": {"type": "string", "description": "本次变更原因（版本化时写进历史）"},
                "contradiction": {"type": "boolean", "description": "是否与旧结论矛盾"},
            },
            "required": ["title", "content", "summary"],
        },
    },
]


class MemoryMCP:
    def __init__(self, config):
        self.cfg = config
        self.store = MemoryStore(config)
        self.adapter = LocalMarkdownAdapter(config["store_dir"])

    # ---------- tool 实现 ----------
    def tool_memory_search(self, args):
        query = (args.get("query") or "").strip()
        if not query:
            return "（query 为空）"
        top = int(args.get("top", 8) or 8)
        results = self.store.search(query, top)
        if not results:
            return "（无命中。可换关键词，或先 reindex）"
        payload = [
            {"score": round(f * 1000, 1), "type": r["type"], "title": r["title"],
             "path": r["path"], "summary": r["summary"],
             "confidence": MemoryStore.parse_confidence(r["confidence"]),
             "provenance": r["provenance"] or None}
            for f, rec, r in results
        ]
        return json.dumps(payload, ensure_ascii=False, indent=2)

    def tool_memory_write(self, args):
        title = args.get("title", "").strip()
        content = args.get("content", "")
        if not title or not content:
            raise ValueError("title 与 content 必填")
        meta = {k: args[k] for k in ("summary", "tags", "type", "provenance",
                                     "confidence", "change_reason") if args.get(k) not in (None, "")}
        if args.get("contradiction"):
            meta["contradiction"] = True
        path = self.adapter.write_page(title, content, meta)
        # 写后立即重建索引，让新记忆当轮即可被 memory_search 命中
        n = self.store.reindex()
        prior = self.adapter._read_prior(path)
        ver = (prior["meta"].get("version") if prior else None) or "1"
        return f"✓ 已写入 {os.path.basename(path)}（version {ver}），已重建索引（{n} 条）"

    def call_tool(self, name, args):
        fn = {"memory_search": self.tool_memory_search,
              "memory_write": self.tool_memory_write}.get(name)
        if fn is None:
            return {"content": [{"type": "text", "text": f"未知 tool: {name}"}], "isError": True}
        try:
            return {"content": [{"type": "text", "text": fn(args)}]}
        except Exception as e:  # 工具级错误回给客户端，不崩服务
            return {"content": [{"type": "text", "text": f"tool 执行出错: {e}"}], "isError": True}

    # ---------- JSON-RPC 分发 ----------
    def handle(self, msg):
        method, mid = msg.get("method"), msg.get("id")
        is_notification = "id" not in msg
        if method == "initialize":
            result = {"protocolVersion": PROTOCOL_VERSION,
                      "capabilities": {"tools": {}}, "serverInfo": SERVER_INFO}
        elif method == "tools/list":
            result = {"tools": TOOLS}
        elif method == "tools/call":
            p = msg.get("params", {})
            result = self.call_tool(p.get("name"), p.get("arguments", {}) or {})
        elif method == "ping":
            result = {}
        elif is_notification:
            return None  # initialized 等通知，无需回复
        else:
            return {"jsonrpc": "2.0", "id": mid,
                    "error": {"code": -32601, "message": f"Method not found: {method}"}}
        if is_notification:
            return None
        return {"jsonrpc": "2.0", "id": mid, "result": result}


def serve(config):
    srv = MemoryMCP(config)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        resp = srv.handle(msg)
        if resp is not None:
            sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            sys.stdout.flush()


def main():
    ap = argparse.ArgumentParser(description="agent-memory-kit MCP server (stdio)")
    ap.add_argument("--config", default=None, help="config.json（复用 retrieval 的 config）")
    a = ap.parse_args()
    serve(load_config(a.config))


if __name__ == "__main__":
    main()
