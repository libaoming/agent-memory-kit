#!/usr/bin/env python3
"""
memory_search.py — agent-memory-kit 的检索注入后端（Store → 检索 → 注入回 Doer）

记忆四角色里的「检索注入」一段：Doer 启动前用它从持久记忆 store 里
按当前任务捞「相关历史教训 top-k」，注入 context。不是把整个记忆灌进去。

算法（纯 Python 标准库，零 pip 依赖，抽自 recall/wiki_search.py）：
  FTS5(trigram) 全文 + LIKE 短词兜底 → RRF 融合 → 时间衰减(updated 半衰期) → top-N

与原版唯一区别：store 路径 / frontmatter 字段名 / 输出格式 / 算法超参
全部从 config.json 注入，Obsidian 只是其中一种配置（output_format=obsidian）。

用法（两段式检索，对齐官方 memory「先读目录再读条目」）：
  python3 memory_search.py --reindex [--config config.json]      # 重建索引
  python3 memory_search.py "区域 班次 首遍吞" [--top 8]           # 第一段：只回 index 行（title/summary/path）
  python3 memory_search.py "区域 班次" --top 3 --full             # 第二段：对真正相关的少量条目附正文全文
索引落在 config 指定的 db_path（默认脚本同目录 .memory_index.db），只读 store。
"""
import os, re, sys, json, sqlite3, argparse, glob
from datetime import date

DEFAULT_CONFIG = {
    # 持久记忆 store 根目录（递归扫 *.md）
    "store_dir": "~/ObsidianVault/wiki",
    # 索引 db 落盘位置（None = 脚本同目录 .memory_index.db）
    "db_path": None,
    # 不入库的文件名（索引/日志类）
    "exclude_files": ["index.md", "log.md"],
    # frontmatter 字段映射：逻辑名 -> 你 store 里的实际字段名
    # provenance = 这条记忆的出处（来源事件/原文/发话人/URL）；confidence = 置信度 0-1
    "frontmatter_fields": {
        "title": "title", "summary": "summary", "tags": "tags",
        "type": "type", "updated": "updated", "created": "created",
        "provenance": "provenance", "confidence": "confidence",
    },
    # FTS5 bm25 列权重（越大越相关）
    "fts_weights": {"title": 10.0, "summary": 6.0, "tags": 4.0, "body": 1.0},
    # LIKE 兜底列加权
    "like_weights": {"title": 3, "summary": 2, "tags": 2, "body": 1},
    "rrf_k": 60,            # RRF 融合常数
    "half_life_days": 90,   # 时间衰减半衰期（天）
    "recency_boost": 0.5,   # 时间衰减做温和加权的系数（不压倒相关性）
    "no_date_weight": 0.3,  # 无日期页的中性权重
    "conf_penalty": 0.5,    # 置信度降权上限：低置信记忆最多打 (1-conf_penalty) 折；无 confidence 字段则中性(不影响)
    # 召回预算闸（borrow 自 TDB applyRecallBudget）：--full 取正文时的单条/总量双预算（字符数）
    "max_chars_per_memory": 6000,
    "max_total_recall_chars": 20000,
    # 输出格式：obsidian | json | markdown
    "output_format": "obsidian",
}


def load_config(path=None):
    cfg = dict(DEFAULT_CONFIG)
    if path:
        with open(os.path.expanduser(path), encoding="utf-8") as f:
            user = json.load(f)
        for k, v in user.items():
            if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                merged = dict(cfg[k]); merged.update(v); cfg[k] = merged
            else:
                cfg[k] = v
    cfg["store_dir"] = os.path.expanduser(cfg["store_dir"])
    if cfg["db_path"]:
        cfg["db_path"] = os.path.expanduser(cfg["db_path"])
    else:
        cfg["db_path"] = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".memory_index.db")
    return cfg


class MemoryStore:
    """参数化的记忆检索后端。构造即拿 config，search()/reindex() 行为与原版一致。"""

    def __init__(self, config=None):
        self.cfg = config or dict(DEFAULT_CONFIG)
        if "store_dir" in self.cfg:
            self.cfg["store_dir"] = os.path.expanduser(self.cfg["store_dir"])
        self.store_dir = self.cfg["store_dir"]
        self.db_path = self.cfg.get("db_path") or os.path.join(
            os.path.dirname(os.path.abspath(__file__)), ".memory_index.db")
        self.fm = self.cfg["frontmatter_fields"]

    # ---------- frontmatter 解析（不依赖 pyyaml）----------
    def parse_md(self, path):
        with open(path, encoding="utf-8", errors="replace") as f:
            txt = f.read()
        fm, body = {}, txt
        if txt.startswith("---"):
            end = txt.find("\n---", 3)
            if end != -1:
                head = txt[3:end]; body = txt[end + 4:]
                for line in head.splitlines():
                    m = re.match(r"^(\w+):\s*(.*)$", line)
                    if m:
                        fm[m.group(1)] = m.group(2).strip().strip('"').strip("'")
        return fm, body

    def _field(self, fm, logical):
        """按 config 的字段映射取 frontmatter 值。"""
        return fm.get(self.fm.get(logical, logical), "")

    @staticmethod
    def scope_of(relpath):
        """目录即 scope：store 根下第一级子目录名（如 org/、task/）；根下散文件 → default。"""
        parts = relpath.replace(os.sep, "/").split("/")
        return parts[0] if len(parts) > 1 else "default"

    def iter_pages(self):
        for p in glob.glob(os.path.join(self.store_dir, "**", "*.md"), recursive=True):
            base = os.path.basename(p)
            if base in self.cfg["exclude_files"]:
                continue
            fm, body = self.parse_md(p)
            title = self._field(fm, "title") or os.path.splitext(base)[0]
            rel = os.path.relpath(p, self.store_dir)
            yield {
                "scope": self.scope_of(rel),
                "path": rel,
                "title": title,
                "summary": self._field(fm, "summary"),
                "tags": self._field(fm, "tags"),
                "type": self._field(fm, "type"),
                "updated": self._field(fm, "updated") or self._field(fm, "created"),
                "provenance": self._field(fm, "provenance"),
                "confidence": self._field(fm, "confidence"),
                "body": body,
            }

    @staticmethod
    def parse_confidence(raw):
        """把 frontmatter 的 confidence 解析成 0-1 浮点；无/不可解析 → None（视为满置信、不降权）。
        支持 '0.9'、'90'（当百分数）、'0.3'。"""
        if raw is None or str(raw).strip() == "":
            return None
        try:
            v = float(str(raw).strip().rstrip("%"))
        except ValueError:
            return None
        if v > 1:
            v = v / 100.0
        return max(0.0, min(1.0, v))

    # ---------- 建索引 ----------
    def reindex(self):
        if os.path.exists(self.db_path):
            os.remove(self.db_path)
        db = sqlite3.connect(self.db_path)
        db.execute("""CREATE VIRTUAL TABLE pages USING fts5(
            path UNINDEXED, scope UNINDEXED, title, summary, tags, type UNINDEXED, updated UNINDEXED,
            provenance UNINDEXED, confidence UNINDEXED,
            body, tokenize='trigram')""")
        n = 0
        for d in self.iter_pages():
            db.execute(
                "INSERT INTO pages(path,scope,title,summary,tags,type,updated,provenance,confidence,body) "
                "VALUES(?,?,?,?,?,?,?,?,?,?)",
                (d["path"], d["scope"], d["title"], d["summary"], d["tags"], d["type"], d["updated"],
                 d["provenance"], d["confidence"], d["body"]))
            n += 1
        db.commit(); db.close()
        return n

    # ---------- 时间衰减 ----------
    def recency(self, updated, half_life):
        try:
            y, m, dd = map(int, updated.split("-")[:3])
            age = (date.today() - date(y, m, dd)).days
            return 0.5 ** (max(age, 0) / half_life)
        except Exception:
            return self.cfg["no_date_weight"]

    # ---------- 检索：FTS + LIKE → RRF + recency ----------
    def search(self, query, top=8, half_life=None, scope=None):
        """scope: None=全部；或 scope 名列表（如 ["org","task"]）——目录即 scope。"""
        half_life = half_life or self.cfg["half_life_days"]
        if not os.path.exists(self.db_path):
            self.reindex()
        db = sqlite3.connect(self.db_path)
        db.row_factory = sqlite3.Row
        terms = [t for t in re.split(r"\s+", query.strip()) if t]

        scope_sql, scope_args = "", []
        if scope:
            scopes = [scope] if isinstance(scope, str) else list(scope)
            scope_sql = " AND scope IN (%s)" % ",".join("?" * len(scopes))
            scope_args = scopes

        fts_rank, like_rank, rows_by_path = {}, {}, {}

        fts_terms = [t for t in terms if len(t) >= 3]
        if fts_terms:
            match = " OR ".join('"%s"' % t.replace('"', '') for t in fts_terms)
            w = self.cfg["fts_weights"]
            # 列序: path,scope,title,summary,tags,type,updated,provenance,confidence,body
            bm25 = f"bm25(pages, 0,0,{w['title']},{w['summary']},{w['tags']},0,0,0,0,{w['body']})"
            try:
                q = (f"SELECT path,scope,title,summary,tags,type,updated,provenance,confidence, {bm25} AS r "
                     f"FROM pages WHERE pages MATCH ?{scope_sql} ORDER BY r LIMIT 60")
                for i, row in enumerate(db.execute(q, (match, *scope_args))):
                    fts_rank[row["path"]] = i
                    rows_by_path[row["path"]] = row
            except sqlite3.OperationalError:
                pass

        lw = self.cfg["like_weights"]
        for t in terms:
            like = f"%{t}%"
            q = ("SELECT path,scope,title,summary,tags,type,updated,provenance,confidence, "
                 f"(CASE WHEN title LIKE ? THEN {lw['title']} ELSE 0 END)+"
                 f"(CASE WHEN summary LIKE ? THEN {lw['summary']} ELSE 0 END)+"
                 f"(CASE WHEN tags LIKE ? THEN {lw['tags']} ELSE 0 END)+"
                 f"(CASE WHEN body LIKE ? THEN {lw['body']} ELSE 0 END) AS hit "
                 f"FROM pages WHERE hit>0{scope_sql}")
            for row in db.execute(q, (like, like, like, like, *scope_args)):
                p = row["path"]
                like_rank[p] = like_rank.get(p, 0) + row["hit"]
                rows_by_path.setdefault(p, row)
        db.close()

        K = self.cfg["rrf_k"]
        boost = self.cfg["recency_boost"]
        penalty = self.cfg["conf_penalty"]
        like_sorted = sorted(like_rank, key=lambda p: -like_rank[p])
        like_pos = {p: i for i, p in enumerate(like_sorted)}
        scored = []
        for p in rows_by_path:
            s = 0.0
            if p in fts_rank: s += 1.0 / (K + fts_rank[p])
            if p in like_pos: s += 1.0 / (K + like_pos[p])
            row = rows_by_path[p]
            rec = self.recency(row["updated"], half_life)
            # 置信度加权：无 confidence → 1.0（不影响，向后兼容）；有则低置信降权、高置信≈不变
            conf = self.parse_confidence(row["confidence"])
            conf_factor = 1.0 if conf is None else (1 - penalty) + penalty * conf
            final = s * (1 + boost * rec) * conf_factor
            scored.append((final, rec, row))
        scored.sort(key=lambda x: -x[0])
        return scored[:top]

    # ---------- 正文取回（两段式第二段） ----------
    def body_of(self, relpath, limit=None):
        """按 index 行的 path 取该条记忆正文（剥 frontmatter，超预算截断）。
        截断按 Python str 切片即 code point 级，天然不撕字符（TDB 在 JS 里要专门防 UTF-16 代理对）；
        截断后缀指路：告诉模型去哪补全文，而非静默丢内容。"""
        if limit is None:
            limit = int(self.cfg.get("max_chars_per_memory", 6000))
        try:
            _, body = self.parse_md(os.path.join(self.store_dir, relpath))
        except OSError:
            return "（正文读取失败）"
        body = body.strip()
        if len(body) > limit:
            body = (body[:limit].rstrip()
                    + f"\n…（截断：memory_search 传 path={relpath} 单取全文，或直接读 store 该文件）")
        return body

    def budgeted_bodies(self, paths):
        """召回预算闸（borrow 自 TDB applyRecallBudget）：单条 + 总量双预算。
        返回 {path: body}。总预算耗尽后，剩余条目给指路占位而非正文——
        排名靠前的记忆拿完整预算，长尾降级成 path 指针，防一次 full 召回打爆 context。"""
        per = int(self.cfg.get("max_chars_per_memory", 6000))
        total = int(self.cfg.get("max_total_recall_chars", 20000))
        remaining = total
        out = {}
        for p in paths:
            if remaining <= 0:
                out[p] = (f"（召回总预算 {total} 字符已用尽——需要时 memory_search 传 "
                          f"path={p} 单取全文，或直接读 store 该文件）")
                continue
            body = self.body_of(p, limit=min(per, remaining))
            remaining -= len(body)
            out[p] = body
        return out

    # ---------- 输出格式 ----------
    def format(self, results, full=False):
        fmt = self.cfg["output_format"]
        bodies = self.budgeted_bodies([r["path"] for _, _, r in results]) if full else {}
        if fmt == "json":
            return json.dumps([
                {"score": round(f * 1000, 1), "type": r["type"], "title": r["title"],
                 "path": r["path"], "scope": r["scope"], "summary": r["summary"],
                 "confidence": self.parse_confidence(r["confidence"]),
                 "provenance": r["provenance"] or None,
                 **({"body": bodies[r["path"]]} if full else {})}
                for f, rec, r in results
            ], ensure_ascii=False, indent=2)
        lines = []
        for f, rec, r in results:
            conf = self.parse_confidence(r["confidence"])
            tail = ""
            if r["scope"] and r["scope"] != "default":
                tail += f"  ⟨{r['scope']}⟩"
            if conf is not None:
                tail += f"  ⟨conf {conf:.2f}⟩"
            if r["provenance"]:
                tail += f"  ⟨src {r['provenance']}⟩"
            if fmt == "markdown":
                s = f"- **{r['title']}** ({r['type'] or '?'}) — {r['summary'][:90]}  `{r['path']}`{tail}"
            else:  # obsidian
                s = f"{f*1000:5.1f} | {r['type'] or '?':9} | [[{r['title']}]] | {r['path']}{tail}"
                if r["summary"]:
                    s += f"\n        ↳ {r['summary'][:90]}"
            if full:
                body = bodies[r["path"]]
                s += "\n" + "\n".join("    " + ln for ln in body.splitlines())
            lines.append(s)
        return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="agent-memory-kit 检索注入后端")
    ap.add_argument("query", nargs="?", default="")
    ap.add_argument("--config", default=None, help="config.json 路径（缺省用内置默认/Obsidian）")
    ap.add_argument("--reindex", action="store_true")
    ap.add_argument("--top", type=int, default=8)
    ap.add_argument("--half-life", type=int, default=None, help="时间衰减半衰期（天）")
    ap.add_argument("--scope", default=None,
                    help="按 scope 过滤（store 根下第一级子目录名，逗号分隔多值，如 org 或 org,task）")
    ap.add_argument("--full", action="store_true",
                    help="两段式第二段：附带命中条目正文全文（默认只出轻量 index 行；配小 --top 用）")
    a = ap.parse_args()

    store = MemoryStore(load_config(a.config))
    if a.reindex:
        n = store.reindex()
        print(f"✓ 已索引 {n} 页 → {store.db_path}", file=sys.stderr)
        if not a.query:
            return
    if not a.query:
        print('用法: python3 memory_search.py "查询词" [--top N] [--scope org,task] [--config c.json] | --reindex')
        return
    scopes = [s.strip() for s in a.scope.split(",") if s.strip()] if a.scope else None
    res = store.search(a.query, a.top, a.half_life, scope=scopes)
    if not res:
        print("（无命中。可换关键词，或 --reindex 后重试）"); return
    print(store.format(res, full=a.full))


if __name__ == "__main__":
    main()
