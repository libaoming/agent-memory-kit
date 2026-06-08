"""prepare.py — agent-memory-kit 的闭环优化 harness（Reflector 的「评估→进化」引擎）

抽自 claude-sdk-playground/autoevolve/prepare.py。唯一改动：把对具体项目
`from prompts import build_system_prompt` 的硬依赖，改成 amk_config.json 的依赖注入
（skill_files / skill_loader_cmd）。其余（karpathy trailer、TSV 记账、--runs 多次平均、
claude CLI 订阅模式）逐字保留，保证抽取前后同 fixture 同分。

后端：claude CLI --print mode（订阅认证，零 API 成本）。

用法：
    python3 prepare.py --config amk_config.json                 # 单次 baseline
    python3 prepare.py --config amk_config.json --eval held_out # held-out 校准
    python3 prepare.py --config amk_config.json --runs 3        # 降噪取均值

amk_config.json 字段：
    project_root      被评 agent 项目根（相对路径基准；默认 config 所在目录）
    skill_files       被进化的 prompt 文件列表（拼接成 system prompt）
    skill_loader_cmd  可选：一条 shell 命令，stdout 即 system prompt（优先于 skill_files）
    judge_file        rubric 文件（要求 judge 输出 {score,pass,reasons}）
    eval_dir          fixture 目录（含 {eval_set}.jsonl）
    results_tsv       记账文件
    agent_model/judge_model/skill_token_limit/role_labels  见默认值

输出末尾固定 karpathy trailer：avg_score / pass_rate / n_cases / runs / skill_chars / skill_over_limit / total_seconds
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

DEFAULT_CONFIG = {
    "project_root": None,            # None = config 文件所在目录
    "skill_files": [],
    "skill_loader_cmd": None,
    "judge_file": "judge.md",
    "eval_dir": "eval",
    "results_tsv": "results.tsv",
    "agent_model": "haiku",
    "judge_model": "sonnet",
    "skill_token_limit": 3000,
    "role_labels": {"user": "user", "assistant": "assistant"},
}

# 去掉 ANTHROPIC_API_KEY，让 claude CLI fallback 到订阅认证
_CLI_ENV = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}

JUDGE_SYSTEM_HEADER = (
    "你是严格但公允的对话质量评估员。"
    "你只评估给定的最后一条 agent_response，按下方 rubric 打分。"
    "输出必须是 valid JSON，不加 markdown 代码围栏，不写多余文字。"
)


def load_config(path):
    cfg = dict(DEFAULT_CONFIG)
    cfg_path = Path(path).expanduser().resolve()
    with cfg_path.open(encoding="utf-8") as f:
        user = json.load(f)
    for k, v in user.items():
        if isinstance(v, dict) and isinstance(cfg.get(k), dict):
            merged = dict(cfg[k]); merged.update(v); cfg[k] = merged
        else:
            cfg[k] = v
    root = cfg["project_root"]
    cfg["project_root"] = Path(root).expanduser().resolve() if root else cfg_path.parent
    return cfg


def estimate_tokens(s: str) -> int:
    return len(s)  # 字符数近似；只用于 over_limit 标志，不影响分数


def load_skill(cfg) -> str:
    """装配被进化的 system prompt：优先跑 skill_loader_cmd，否则拼接 skill_files。"""
    root = cfg["project_root"]
    cmd = cfg.get("skill_loader_cmd")
    if cmd:
        out = subprocess.run(cmd, shell=True, capture_output=True, text=True,
                             cwd=str(root), env=_CLI_ENV, timeout=60)
        if out.returncode != 0:
            raise RuntimeError(f"skill_loader_cmd error: {out.stderr[:300]}")
        return out.stdout
    parts = []
    for rel in cfg.get("skill_files", []):
        p = (root / rel)
        if p.exists():
            parts.append(p.read_text(encoding="utf-8"))
        else:
            print(f"WARN: skill_file 不存在: {p}", file=sys.stderr)
    if not parts:
        print("ERROR: skill 为空，检查 skill_files / skill_loader_cmd", file=sys.stderr)
        sys.exit(1)
    return "\n\n".join(parts)


def load_cases(cfg, eval_set: str) -> list[dict]:
    path = cfg["project_root"] / cfg["eval_dir"] / f"{eval_set}.jsonl"
    if not path.exists():
        print(f"ERROR: eval 集不存在: {path}", file=sys.stderr)
        sys.exit(1)
    cases: list[dict] = []
    with path.open(encoding="utf-8") as f:
        for line_no, raw in enumerate(f, 1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                cases.append(json.loads(raw))
            except json.JSONDecodeError as e:
                print(f"ERROR: {path}:{line_no} JSON 解析失败: {e}", file=sys.stderr)
                sys.exit(1)
    if not cases:
        print(f"ERROR: eval 集为空: {path}", file=sys.stderr)
        sys.exit(1)
    return cases


def _call_claude_cli(model: str, prompt: str, timeout: int = 120) -> str:
    result = subprocess.run(
        ["claude", "-p", "--model", model],
        input=prompt, capture_output=True, text=True, env=_CLI_ENV, timeout=timeout,
    )
    if result.returncode != 0:
        raise RuntimeError(f"claude CLI error (exit {result.returncode}): {result.stderr[:300]}")
    return result.stdout.strip()


def run_agent(cfg, system: str, messages: list[dict]) -> tuple[str, dict]:
    labels = cfg["role_labels"]
    if len(messages) == 1 and messages[0]["role"] == "user":
        user_part = messages[0]["content"]
    else:
        parts = []
        for msg in messages:
            role = labels.get(msg["role"], msg["role"])
            parts.append(f"{role}: {msg['content']}")
        user_part = "以下是对话历史，请回复最后一条用户消息：\n\n" + "\n".join(parts)
    full_prompt = f"<instructions>\n{system}\n</instructions>\n\n{user_part}"
    text = _call_claude_cli(cfg["agent_model"], full_prompt)
    return text, {"input": 0, "output": 0}


def _strip_code_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        if text.endswith("```"):
            text = text.rsplit("```", 1)[0]
    return text.strip()


def judge_one(cfg, rubric: str, case: dict, response: str) -> dict:
    system = JUDGE_SYSTEM_HEADER + "\n\n" + rubric
    judge_user = (
        "<rubric>\n" f"{rubric}\n" "</rubric>\n\n"
        "<case_context>\n"
        f"case_id: {case.get('id', '?')}\n"
        f"stage: {case.get('stage', '?')}\n"
        f"expected: {case.get('expected', 'N/A')}\n\n"
        "对话历史（最后一条 user 是触发 agent 回复的那条）：\n"
        f"{json.dumps(case['messages'], ensure_ascii=False, indent=2)}\n"
        "</case_context>\n\n"
        "<agent_response>\n" f"{response}\n" "</agent_response>\n\n"
        "请严格按 rubric 评分。输出必须是单个完整的 JSON 对象（不加 markdown 围栏），格式：\n"
        '{"score": <0-10 整数>, "pass": <bool, score>=7 为 true>, "reasons": "<≤ 80 字符的一句话总结>"}\n\n'
        "硬约束：\n"
        "- reasons 字段必须 ≤ 80 字符，越短越好\n"
        "- 不要在 JSON 外写任何文字\n"
        "- 不要修改自己已写的分数"
    )
    full_prompt = f"<instructions>\n{system}\n</instructions>\n\n{judge_user}"
    text = _strip_code_fence(_call_claude_cli(cfg["judge_model"], full_prompt))
    try:
        verdict = json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r'"score"\s*:\s*(\d+)', text)
        if m:
            score = int(m.group(1))
            return {"score": score, "pass": score >= 7,
                    "reasons": f"[parse fallback] judge JSON 截断，score={score}"}
        return {"score": 0, "pass": False, "reasons": f"judge JSON parse failed: {text[:120]}"}
    try:
        verdict["score"] = int(verdict.get("score", 0))
    except (TypeError, ValueError):
        verdict["score"] = 0
    verdict["pass"] = bool(verdict.get("pass", verdict["score"] >= 7))
    verdict.setdefault("reasons", "")
    return verdict


def evaluate(cfg, eval_set: str, runs: int = 1) -> int:
    if not shutil.which("claude"):
        print("ERROR: claude CLI 不在 PATH 中", file=sys.stderr)
        return 1
    judge_file = cfg["project_root"] / cfg["judge_file"]
    if not judge_file.exists():
        print(f"ERROR: judge 文件不存在: {judge_file}", file=sys.stderr)
        return 1

    rubric = judge_file.read_text(encoding="utf-8")
    skill = load_skill(cfg)
    skill_tokens = estimate_tokens(skill)
    cases = load_cases(cfg, eval_set)

    print(f"[amk-evolve] eval_set={eval_set} cases={len(cases)} runs={runs} "
          f"agent={cfg['agent_model']} judge={cfg['judge_model']} skill_chars={skill_tokens} "
          f"backend=cli-subscription", file=sys.stderr)

    t0 = time.time()
    run_avgs: list[float] = []
    run_pass_rates: list[float] = []

    for run_idx in range(1, runs + 1):
        if runs > 1:
            print(f"\n  ── run {run_idx}/{runs} ──", file=sys.stderr)
        scores: list[dict] = []
        for i, case in enumerate(cases, 1):
            case_id = case.get("id", f"case-{i}")
            try:
                response, _usage = run_agent(cfg, skill, case["messages"])
                verdict = judge_one(cfg, rubric, case, response)
            except Exception as e:  # noqa: BLE001
                verdict = {"score": 0, "pass": False, "reasons": f"crash: {type(e).__name__}: {e}"}
                response = ""
            scores.append(verdict)
            mark = "✓" if verdict["pass"] else "✗"
            snippet = (response or "").replace("\n", " ")[:60]
            print(f"  [{i:>2}/{len(cases)}] {mark} score={verdict['score']:>2} "
                  f"{case_id} | resp: {snippet} | judge: {verdict['reasons'][:80]}", file=sys.stderr)

        n = len(scores)
        r_avg = sum(s["score"] for s in scores) / n if n else 0.0
        r_pass = sum(1 for s in scores if s["pass"]) / n if n else 0.0
        run_avgs.append(r_avg); run_pass_rates.append(r_pass)
        if runs > 1:
            print(f"  run {run_idx}: avg={r_avg:.2f} pass={r_pass:.2f}", file=sys.stderr)

    avg = sum(run_avgs) / len(run_avgs)
    pass_rate = sum(run_pass_rates) / len(run_pass_rates)
    elapsed = time.time() - t0
    over_limit = 1 if skill_tokens > cfg["skill_token_limit"] else 0

    print("---")
    print(f"avg_score:        {avg:.4f}")
    print(f"pass_rate:        {pass_rate:.4f}")
    print(f"n_cases:          {n}")
    print(f"runs:             {runs}")
    print(f"skill_chars:      {skill_tokens}")
    print(f"skill_over_limit: {over_limit}")
    print(f"total_seconds:    {elapsed:.1f}")
    if runs > 1:
        print(f"score_spread:     {max(run_avgs) - min(run_avgs):.4f}")

    _append_tsv(cfg, eval_set, avg, pass_rate, runs, skill_tokens, elapsed)
    return 0


def _append_tsv(cfg, eval_set, avg, pass_rate, runs, skill_tokens, elapsed) -> None:
    import datetime
    import subprocess as _sp
    tsv = cfg["project_root"] / cfg["results_tsv"]
    write_header = not tsv.exists()
    commit = "uncommitted"
    try:
        commit = _sp.run(["git", "rev-parse", "--short", "HEAD"],
                         capture_output=True, text=True, cwd=str(cfg["project_root"]),
                         timeout=5).stdout.strip() or "unknown"
    except Exception:
        pass
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    with tsv.open("a", encoding="utf-8") as f:
        if write_header:
            f.write("timestamp\tcommit\teval_set\tavg_score\tpass_rate\truns\tskill_chars\tseconds\tstatus\tnote\n")
        f.write(f"{ts}\t{commit}\t{eval_set}\t{avg:.4f}\t{pass_rate:.4f}\t{runs}\t{skill_tokens}\t{elapsed:.0f}\t\t\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="agent-memory-kit 闭环优化 harness")
    parser.add_argument("--config", required=True, help="amk_config.json 路径")
    parser.add_argument("--eval", default="train_set", help="eval 集名（默认 train_set）")
    parser.add_argument("--runs", type=int, default=1, help="跑几轮取均值（降噪，推荐 3）")
    args = parser.parse_args()
    cfg = load_config(args.config)
    return evaluate(cfg, args.eval, runs=args.runs)


if __name__ == "__main__":
    sys.exit(main())
