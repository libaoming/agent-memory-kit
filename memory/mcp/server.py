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
import os, re, sys, json, argparse

# 复用 kit 的检索后端 + 持久层适配器（兄弟目录，脚手架式动态挂载）
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "retrieval"))
sys.path.insert(0, os.path.join(_HERE, "..", "librarian"))
from memory_search import MemoryStore, load_config  # noqa: E402
from adapter import LocalMarkdownAdapter  # noqa: E402

PROTOCOL_VERSION = "2024-11-05"
SERVER_INFO = {"name": "agent-memory-kit", "version": "0.2.0"}


def _flag(v, default=False):
    """MCP 客户端常把 boolean 发成字符串——"false" 按 truthy 判会静默绕闸，显式白名单解析。"""
    if v is None:
        return default
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in ("true", "1", "yes", "on")


def _shingle_query(text, n=3, stride=2, max_terms=16):
    """冲突闸召回用：未分词长 token（典型=整句中文摘要）切成 3 字 shingle。
    检索是空格切词 + trigram FTS/LIKE 子串——整句中文是单一长 term，召回必空（假阴性）；
    shingle 后 FTS 与 LIKE 都吃得动。短 token（已分词/英文单词）原样保留。"""
    terms = []
    for tok in re.split(r"\s+", (text or "").strip()):
        if not tok:
            continue
        if len(tok) <= 4:
            terms.append(tok)
        else:
            terms.extend(tok[i:i + n] for i in range(0, len(tok) - n + 1, stride))
    return " ".join(terms[:max_terms]) or text

TOOLS = [
    {
        "name": "memory_search",
        "description": ("检索运行时记忆 store，按当前任务返回 top-k 相关历史教训（当前视图，"
                        "带 confidence 置信度与 provenance 出处）。走两段式：默认只回轻量 index 行"
                        "（title/summary/path），对真正相关的少量条目再传 full=true 取正文——"
                        "别第一段就 full 全量灌 context。full 的正文有单条+总量双预算，"
                        "超预算会截断/降级为指针；要某条完整正文，传 path 单独取（预算最宽）。"),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "任务/场景关键词，空格分隔"},
                "top": {"type": "integer", "description": "返回条数，默认 8", "default": 8},
                "full": {"type": "boolean", "default": False,
                         "description": "两段式第二段：附带命中条目正文全文（配小 top 用）"},
                "path": {"type": "string",
                         "description": "按 index 行的 path 单取一条的完整正文（独占整个召回预算，"
                                        "传它时忽略 query/top/full）"},
            },
            "required": [],
        },
    },
    {
        "name": "memory_write",
        "description": ("把一条新教训落盘为记忆。同名记忆再写且内容有实质变化时自动版本化——"
                        "旧 claim 归档进历史段（非覆盖），可 diff。传 provenance 记出处、"
                        "confidence 记置信度（检索按它降权）、change_reason 记变更原因、"
                        "contradiction=true 标与旧结论矛盾。"
                        "新 title 首写会过冲突闸：若存在相似旧记忆，先返回候选让你判定四元组决策"
                        "（store=确认新建，重发并传 dedup_checked=true；update/merge=同一件事，"
                        "改用已有 title 重写；skip=已覆盖，放弃）。"),
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
                "dedup_checked": {"type": "boolean",
                                  "description": "冲突闸判定为 store（确认与候选都不是同一件事）后传 true 强制新建"},
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
        # 挂载接口两槽位：steering（「记什么」声明，注入 memory_write 描述）+ read_only（只读挂载不暴露写）
        self.read_only = _flag(config.get("read_only"))
        # 冲突闸（borrow 自 TDB batchDedup）：新 title 首写先撞相似旧记忆，默认开
        self.dedup_gate = _flag(config.get("dedup_gate", True), default=True)
        steering = (config.get("steering") or "").strip()
        self.tools = []
        for t in TOOLS:
            if t["name"] == "memory_write":
                if self.read_only:
                    continue
                if steering:
                    t = dict(t)
                    t["description"] = f"【记什么·steering】{steering}\n{t['description']}"
            self.tools.append(t)

    # ---------- tool 实现 ----------
    def tool_memory_search(self, args):
        # path 单取：一条独占整个总预算——「截断指路」的接盘口，纯 MCP 客户端也能拿到全文
        relpath = (args.get("path") or "").strip()
        if relpath:
            total = int(self.cfg.get("max_total_recall_chars", 20000))
            return json.dumps({"path": relpath, "body": self.store.body_of(relpath, limit=total)},
                              ensure_ascii=False, indent=2)
        query = (args.get("query") or "").strip()
        if not query:
            return "（query 为空）"
        top = int(args.get("top", 8) or 8)
        full = bool(args.get("full"))
        results = self.store.search(query, top)
        if not results:
            return "（无命中。可换关键词，或先 reindex）"
        bodies = self.store.budgeted_bodies([r["path"] for _, _, r in results]) if full else {}
        payload = [
            {"score": round(f * 1000, 1), "type": r["type"], "title": r["title"],
             "path": r["path"], "summary": r["summary"],
             "confidence": MemoryStore.parse_confidence(r["confidence"]),
             "provenance": r["provenance"] or None,
             **({"body": bodies[r["path"]]} if full else {})}
            for f, rec, r in results
        ]
        return json.dumps(payload, ensure_ascii=False, indent=2)

    def tool_memory_write(self, args):
        if self.read_only:
            raise ValueError("store 为只读挂载（config read_only=true），memory_write 不可用")
        title = args.get("title", "").strip()
        content = args.get("content", "")
        if not title or not content:
            raise ValueError("title 与 content 必填")

        # 冲突闸（四元组决策，borrow 自 TDB batchDedup）：只拦「新 title 首写」——
        # 同名再写本来就是 update/merge 语义，走版本化，不重复过闸。
        # 「同名」判据 = find_by_title 按 frontmatter title 精确比对（全树含 scope 子目录）：
        # 用 path 存在性冒充会两头出错——task/ 下同名文件看不见（update 死锁）、
        # slug 碰撞的不同 title 又被误放行。
        if (self.dedup_gate and not _flag(args.get("dedup_checked"))
                and self.adapter.find_by_title(title) is None):
            query = _shingle_query(f"{title} {args.get('summary', '')}".strip())
            cands = self.store.search(query, top=5)
            if cands:
                lines = [f"- [[{r['title']}]]（{r['path']}）— {(r['summary'] or '')[:60]}"
                         for _, _, r in cands]
                return ("⚠️ 冲突闸：发现相似旧记忆，先判定这条新记忆与它们的关系再写：\n"
                        + "\n".join(lines) + "\n\n"
                        "- store  = 都不是同一件事 → 原参数重发并传 dedup_checked=true\n"
                        "- update = 同一件事的新结论 → 改用上面已有 title 重写（自动版本化归档旧 claim）\n"
                        "- merge  = 与旧条互补 → 改用旧 title 重写，正文写融合后内容，"
                        "change_reason 注明 merge 来源\n"
                        "- skip   = 已被旧条覆盖 → 放弃本次写入")

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
            result = {"tools": self.tools}
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
