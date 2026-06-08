#!/usr/bin/env python3
"""
memory_search.py — agent-memory-kit 的检索注入后端（Store → 检索 → 注入回 Doer）

记忆四角色里的「检索注入」一段：Doer 启动前用它从持久记忆 store 里
按当前任务捞「相关历史教训 top-k」，注入 context。不是把整个记忆灌进去。

算法（纯 Python 标准库，零 pip 依赖，抽自 recall/wiki_search.py）：
  FTS5(trigram) 全文 + LIKE 短词兜底 → RRF 融合 → 时间衰减(updated 半衰期) → top-N

与原版唯一区别：store 路径 / frontmatter 字段名 / 输出格式 / 算法超参
全部从 config.json 注入，Obsidian 只是其中一种配置（output_format=obsidian）。

用法：
  python3 memory_search.py --reindex [--config config.json]      # 重建索引
  python3 memory_search.py "区域 班次 首遍吞" [--top 8] [--config config.json]
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
    "frontmatter_fields": {
        "title": "title", "summary": "summary", "tags": "tags",
        "type": "type", "updated": "updated", "created": "created",
    },
    # FTS5 bm25 列权重（越大越相关）
    "fts_weights": {"title": 10.0, "summary": 6.0, "tags": 4.0, "body": 1.0},
    # LIKE 兜底列加权
    "like_weights": {"title": 3, "summary": 2, "tags": 2, "body": 1},
    "rrf_k": 60,            # RRF 融合常数
    "half_life_days": 90,   # 时间衰减半衰期（天）
    "recency_boost": 0.5,   # 时间衰减做温和加权的系数（不压倒相关性）
    "no_date_weight": 0.3,  # 无日期页的中性权重
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

    def iter_pages(self):
        for p in glob.glob(os.path.join(self.store_dir, "**", "*.md"), recursive=True):
            base = os.path.basename(p)
            if base in self.cfg["exclude_files"]:
                continue
            fm, body = self.parse_md(p)
            title = self._field(fm, "title") or os.path.splitext(base)[0]
            yield {
                "path": os.path.relpath(p, self.store_dir),
                "title": title,
                "summary": self._field(fm, "summary"),
                "tags": self._field(fm, "tags"),
                "type": self._field(fm, "type"),
                "updated": self._field(fm, "updated") or self._field(fm, "created"),
                "body": body,
            }

    # ---------- 建索引 ----------
    def reindex(self):
        if os.path.exists(self.db_path):
            os.remove(self.db_path)
        db = sqlite3.connect(self.db_path)
        db.execute("""CREATE VIRTUAL TABLE pages USING fts5(
            path UNINDEXED, title, summary, tags, type UNINDEXED, updated UNINDEXED,
            body, tokenize='trigram')""")
        n = 0
        for d in self.iter_pages():
            db.execute("INSERT INTO pages(path,title,summary,tags,type,updated,body) VALUES(?,?,?,?,?,?,?)",
                       (d["path"], d["title"], d["summary"], d["tags"], d["type"], d["updated"], d["body"]))
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
    def search(self, query, top=8, half_life=None):
        half_life = half_life or self.cfg["half_life_days"]
        if not os.path.exists(self.db_path):
            self.reindex()
        db = sqlite3.connect(self.db_path)
        db.row_factory = sqlite3.Row
        terms = [t for t in re.split(r"\s+", query.strip()) if t]

        fts_rank, like_rank, rows_by_path = {}, {}, {}

        fts_terms = [t for t in terms if len(t) >= 3]
        if fts_terms:
            match = " OR ".join('"%s"' % t.replace('"', '') for t in fts_terms)
            w = self.cfg["fts_weights"]
            # 列序: path,title,summary,tags,type,updated,body
            bm25 = f"bm25(pages, 0,{w['title']},{w['summary']},{w['tags']},0,0,{w['body']})"
            try:
                q = (f"SELECT path,title,summary,tags,type,updated, {bm25} AS r "
                     "FROM pages WHERE pages MATCH ? ORDER BY r LIMIT 60")
                for i, row in enumerate(db.execute(q, (match,))):
                    fts_rank[row["path"]] = i
                    rows_by_path[row["path"]] = row
            except sqlite3.OperationalError:
                pass

        lw = self.cfg["like_weights"]
        for t in terms:
            like = f"%{t}%"
            q = ("SELECT path,title,summary,tags,type,updated, "
                 f"(CASE WHEN title LIKE ? THEN {lw['title']} ELSE 0 END)+"
                 f"(CASE WHEN summary LIKE ? THEN {lw['summary']} ELSE 0 END)+"
                 f"(CASE WHEN tags LIKE ? THEN {lw['tags']} ELSE 0 END)+"
                 f"(CASE WHEN body LIKE ? THEN {lw['body']} ELSE 0 END) AS hit "
                 "FROM pages WHERE hit>0")
            for row in db.execute(q, (like, like, like, like)):
                p = row["path"]
                like_rank[p] = like_rank.get(p, 0) + row["hit"]
                rows_by_path.setdefault(p, row)
        db.close()

        K = self.cfg["rrf_k"]
        boost = self.cfg["recency_boost"]
        like_sorted = sorted(like_rank, key=lambda p: -like_rank[p])
        like_pos = {p: i for i, p in enumerate(like_sorted)}
        scored = []
        for p in rows_by_path:
            s = 0.0
            if p in fts_rank: s += 1.0 / (K + fts_rank[p])
            if p in like_pos: s += 1.0 / (K + like_pos[p])
            row = rows_by_path[p]
            rec = self.recency(row["updated"], half_life)
            final = s * (1 + boost * rec)
            scored.append((final, rec, row))
        scored.sort(key=lambda x: -x[0])
        return scored[:top]

    # ---------- 输出格式 ----------
    def format(self, results):
        fmt = self.cfg["output_format"]
        if fmt == "json":
            return json.dumps([
                {"score": round(f * 1000, 1), "type": r["type"], "title": r["title"],
                 "path": r["path"], "summary": r["summary"]}
                for f, rec, r in results
            ], ensure_ascii=False, indent=2)
        lines = []
        for f, rec, r in results:
            if fmt == "markdown":
                s = f"- **{r['title']}** ({r['type'] or '?'}) — {r['summary'][:90]}  `{r['path']}`"
            else:  # obsidian
                s = f"{f*1000:5.1f} | {r['type'] or '?':9} | [[{r['title']}]] | {r['path']}"
                if r["summary"]:
                    s += f"\n        ↳ {r['summary'][:90]}"
            lines.append(s)
        return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="agent-memory-kit 检索注入后端")
    ap.add_argument("query", nargs="?", default="")
    ap.add_argument("--config", default=None, help="config.json 路径（缺省用内置默认/Obsidian）")
    ap.add_argument("--reindex", action="store_true")
    ap.add_argument("--top", type=int, default=8)
    ap.add_argument("--half-life", type=int, default=None, help="时间衰减半衰期（天）")
    a = ap.parse_args()

    store = MemoryStore(load_config(a.config))
    if a.reindex:
        n = store.reindex()
        print(f"✓ 已索引 {n} 页 → {store.db_path}", file=sys.stderr)
        if not a.query:
            return
    if not a.query:
        print('用法: python3 memory_search.py "查询词" [--top N] [--config c.json] | --reindex')
        return
    res = store.search(a.query, a.top, a.half_life)
    if not res:
        print("（无命中。可换关键词，或 --reindex 后重试）"); return
    print(store.format(res))


if __name__ == "__main__":
    main()
