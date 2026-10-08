#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Alessandro Carosia

"""The shape of the `silica_search` reply, measured through `silica-core repl`'s
loop with a cheap OpenAI-compatible model instead of `claude -p`: same tasks,
rubrics and preamble as scripts/baseline.py, only the four read tools, the
dense leg on (local-hybrid, potion), one variable per arm.

    uv run --extra dense scripts/bench_repl.py --prepare --arms base,lean,wide --reps 3 --jobs 6
    uv run --extra dense scripts/bench_repl.py --judge docs/baseline/<folder>
    uv run --extra dense scripts/bench_repl.py --compare base lean docs/baseline/<folder>

Arms (the tool's docstring is identical in every arm):
  base  the reply as shipped: k=5, width=600, `documents`, `matched_terms`
  lean  no `documents` block and no per-hit `matched_terms`; coverage,
        terms_absent, scope, dense and index stay (the honest zero, minimal)
  wide  width defaults to 1500 instead of 600, everything else as base

What a run records: model calls (turns), tool calls by name, chars of every
tool result and of the search replies alone, prompt/cached/completion
tokens summed over the calls, the provider's cost, the rubric score, the
answer, the whole transcript under streams/. The model and key come from
SILICA_MODEL and ~/.silica/.env as for `silica-core repl`.

The REPL truncates a tool result at 12,000 chars, under a wide reply; here
the cap is 100,000 chars (Claude Code's is 25,000 tokens), the same in every
arm, and a truncation is counted.
"""
from __future__ import annotations

import argparse
import collections
import concurrent.futures
import copy
import hashlib
import json
import os
import random
import statistics
import subprocess
import sys
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
import baseline  # noqa: E402  tasks, rubric, preamble, corpus identity

ARMS = {
    "base": "the reply as shipped (k=5, width=600, documents, matched_terms)",
    "lean": "no documents block, no per-hit matched_terms; coverage, terms_absent, scope, dense, index stay",
    "wide": "width defaults to 1500 instead of 600, everything else as base",
}
TOOLS = ("silica_files", "silica_search", "silica_read", "silica_code_pack")  # baseline.SILICA_TOOLS, unprefixed
ENV = {"SILICA_INDEX_CODE": "1", "SILICA_EMBEDDING_MODEL": "model2vec/minishlab/potion-retrieval-32M"}
RESULT_CAP = 100_000
RETRY_ON = ("429", "500", "502", "503", "504", "524")
ALL_TASKS = baseline.TASKS + baseline.HARD_TASKS + baseline.SWE_TASKS


class Shaped:
    """The search tool under an arm: `run` and `json_schema` are what the loop
    calls; the reply changes, the docstring does not. `Tool` is read-only."""

    def __init__(self, tool, arm: str):
        if arm not in ARMS:
            raise ValueError(f"unknown arm {arm!r}")
        self.tool, self.arm, self.name, self.description = tool, arm, tool.name, tool.description

    def json_schema(self) -> dict:
        s = copy.deepcopy(self.tool.json_schema())
        if self.arm == "wide":
            s["function"]["parameters"]["properties"]["width"]["default"] = 1500
        return s

    def run(self, **kw) -> str:
        if self.arm == "wide":
            kw.setdefault("width", 1500)
        out = self.tool.run(**kw)
        if self.arm == "lean":
            d = json.loads(out)
            if "hits" in d:
                d.pop("documents", None)
                for h in d["hits"]:
                    h.pop("matched_terms", None)
            out = json.dumps(d, ensure_ascii=False, default=str)
        return out


def usage_post(calls: list[dict]):
    """A `post` for repl.complete that asks the provider for usage and cost
    on the last chunk and keeps one dict per model call. The stream is
    buffered whole, so a 429/5xx or a transport error (DNS, a read timeout
    mid-stream: 14 of 324 runs on 2026-09-16) retries the call from scratch
    without duplicating deltas; the tokens of a failed attempt are not counted."""
    import httpx

    from silica_core import repl

    def post(base, key, payload):
        payload = {**payload, "stream_options": {"include_usage": True}, "usage": {"include": True}}
        for attempt in range(4):
            try:
                chunks = list(repl._post_stream(base, key, payload))
                break
            except (RuntimeError, httpx.HTTPError) as e:
                if attempt == 3 or not (isinstance(e, httpx.HTTPError) or str(e).startswith(RETRY_ON)):
                    raise
                time.sleep(5 * 2 ** attempt)
        calls.append(next((c["usage"] for c in reversed(chunks) if c.get("usage")), {}))
        yield from chunks
    return post


def warm() -> dict:
    from silica_core import embeddings
    embeddings.set_retrieval("local-hybrid")
    t0 = time.time()
    embeddings.warm_up().join()
    return {**embeddings.warmup_state(), "seconds": round(time.time() - t0, 1)}


def one(task: dict, arm: str, rep: int, out: Path) -> dict:
    """One run in this process: SILICA_VAULT is already the task's folder."""
    from silica_core import repl
    from silica_core.config import CONFIG
    from silica_core.ui.mcp import exposed_tools

    dense = warm()
    registry = {n: t for n, t in exposed_tools().items() if n in TOOLS}
    registry["silica_search"] = Shaped(registry["silica_search"], arm)
    repl.TOOL_RESULT_CHARS = RESULT_CAP
    calls: list[dict] = []
    log: list[dict] = []

    def on_tool(name, args, result):
        log.append({"tool": name, "args": {k: str(v)[:120] for k, v in args.items()}, "chars": len(result),
                    "truncated": len(result) > RESULT_CAP, "error": '"error"' in result[:200]})

    messages = [{"role": "system", "content": repl.SYSTEM.format(root=CONFIG.vault_path)},
                {"role": "user", "content": baseline.PREAMBLE + task["prompt"]}]
    t0 = time.time()
    try:
        answer = repl.run_turn(messages, registry, lambda s: None, on_tool, post=usage_post(calls))
        error = ""
    except Exception as e:  # the endpoint's failure is the run's result
        answer, error = "", f"{type(e).__name__}: {e}"
    duration = round(time.time() - t0, 1)
    (out / "streams").mkdir(exist_ok=True)
    (out / "streams" / f"{task['id']}-{arm}-{rep}.json").write_text(
        json.dumps({"messages": messages, "tools": log, "calls": calls}, ensure_ascii=False, indent=1))
    tools = collections.Counter(t["tool"] for t in log)
    ok, missing = baseline.score(task, answer)

    def total(key: str, sub: str = "") -> int:
        return sum((c.get(sub, {}) or {}).get(key, 0) if sub else c.get(key, 0) for c in calls)
    return {"task": task["id"], "kind": task["kind"], "arm": arm, "rep": rep, "model": CONFIG.model,
            "error": error, "dense": dense.get("state"), "turns": len(calls),
            "tools": dict(tools), "tool_calls": sum(tools.values()),
            "search_calls": tools.get("silica_search", 0), "read_calls": tools.get("silica_read", 0),
            "tool_errors": sum(t["error"] for t in log), "truncated": sum(t["truncated"] for t in log),
            "search_chars": sum(t["chars"] for t in log if t["tool"] == "silica_search"),
            "tool_chars": sum(t["chars"] for t in log),
            "prompt_tokens": total("prompt_tokens"), "cached_tokens": total("cached_tokens", "prompt_tokens_details"),
            "completion_tokens": total("completion_tokens"),
            "reasoning_tokens": total("reasoning_tokens", "completion_tokens_details"),
            "cost_usd": round(sum(c.get("cost", 0) or 0 for c in calls), 6), "duration_s": duration,
            "score": ok, "missing": missing, "answer": answer}


def spawn(task: dict, arm: str, rep: int, out: Path, timeout: int) -> dict:
    env = {**os.environ, **ENV, "SILICA_VAULT": str(task["cwd"])}
    cmd = [sys.executable, __file__, "--one", task["id"], arm, str(rep), "--out", str(out)]
    try:
        p = subprocess.run(cmd, cwd=task["cwd"], env=env, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"task": task["id"], "kind": task["kind"], "arm": arm, "rep": rep, "error": f"timeout {timeout}s",
                "turns": None, "tools": {}, "tool_calls": 0, "search_calls": 0, "read_calls": 0, "tool_errors": 0,
                "truncated": 0, "search_chars": 0, "tool_chars": 0, "prompt_tokens": None, "cached_tokens": None,
                "completion_tokens": None, "reasoning_tokens": None, "cost_usd": None, "duration_s": timeout,
                "score": 0, "missing": ["timeout"], "answer": ""}
    line = p.stdout.strip().splitlines()[-1] if p.stdout.strip() else ""
    try:
        return json.loads(line)
    except ValueError:
        return {"task": task["id"], "kind": task["kind"], "arm": arm, "rep": rep,
                "error": f"exit {p.returncode}: {p.stderr[-600:]}", "turns": None, "tools": {}, "tool_calls": 0,
                "search_calls": 0, "read_calls": 0, "tool_errors": 0, "truncated": 0, "search_chars": 0,
                "tool_chars": 0, "prompt_tokens": None, "cached_tokens": None, "completion_tokens": None,
                "reasoning_tokens": None, "cost_usd": None, "duration_s": None, "score": 0,
                "missing": ["crash"], "answer": ""}


def load(folder: Path) -> list[dict]:
    """One row per (task, arm, rep), the last written: a resumed grid redoes an errored run after its row."""
    p = folder / "runs.jsonl"
    rows: dict[tuple, dict] = {}
    for l in (p.read_text().splitlines() if p.exists() else []):
        if l.strip():
            r = json.loads(l)
            rows[(r["task"], r["arm"], r["rep"])] = r
    return list(rows.values())


def load_judge(folder: Path) -> dict:
    p = folder / "judge.jsonl"
    out = {}
    if p.exists():
        for l in p.read_text().splitlines():
            if l.strip():
                j = json.loads(l)
                out[(j["task"], j["arm"], j["rep"])] = j
    return out


def mean(rows, key):
    vals = [r[key] for r in rows if isinstance(r.get(key), (int, float))]
    return statistics.mean(vals) if vals else float("nan")


def summarize(folder: Path) -> str:
    rows = load(folder)
    judge = load_judge(folder)
    for r in rows:
        j = judge.get((r["task"], r["arm"], r["rep"]))
        r["judge"] = j["score"] if j and j.get("score") is not None else None
    arms = [a for a in ARMS if any(r["arm"] == a for r in rows)]
    lines = ["| kind | arm | n | score | judge | cost $ | turns | tools | search | read | prompt tok | cached | out tok | "
             "search chars | trunc | s | errors |", "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for kind in ("code", "docs", "hard", "swe", "all"):
        for arm in arms:
            rs = [r for r in rows if r["arm"] == arm and (kind == "all" or r["kind"] == kind)]
            if not rs:
                continue
            errors, rs = sum(1 for r in rs if r.get("error")), [r for r in rs if not r.get("error")]
            lines.append(f"| {kind} | {arm} | {len(rs)} | {mean(rs, 'score'):.2f} | {mean(rs, 'judge'):.1f} | "
                         f"{mean(rs, 'cost_usd'):.4f} | {mean(rs, 'turns'):.1f} | {mean(rs, 'tool_calls'):.1f} | "
                         f"{mean(rs, 'search_calls'):.1f} | {mean(rs, 'read_calls'):.1f} | "
                         f"{mean(rs, 'prompt_tokens'):,.0f} | {mean(rs, 'cached_tokens'):,.0f} | "
                         f"{mean(rs, 'completion_tokens'):,.0f} | {mean(rs, 'search_chars'):,.0f} | "
                         f"{mean(rs, 'truncated'):.2f} | {mean(rs, 'duration_s'):.0f} | {errors} |")
    lines.append("")
    lines.append("| task | " + " | ".join(f"{a} score" for a in arms) + " | " + " | ".join(f"{a} judge" for a in arms) + " |")
    lines.append("|---|" + "---|" * (2 * len(arms)))
    for t in ALL_TASKS:
        rs = [r for r in rows if r["task"] == t["id"] and not r.get("error")]
        if not rs:
            continue
        cells = [f"{mean([r for r in rs if r['arm'] == a], 'score'):.2f}" for a in arms]
        cells += [f"{mean([r for r in rs if r['arm'] == a], 'judge'):.0f}" for a in arms]
        lines.append(f"| {t['id']} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def ci(diffs, n=10000, seed=0):
    rnd = random.Random(seed)
    means = sorted(statistics.mean(rnd.choices(diffs, k=len(diffs))) for _ in range(n))
    return means[int(0.025 * n)], means[int(0.975 * n)]


def compare(folder: Path, a: str, b: str, kind: str = "") -> str:
    rows = [r for r in load(folder) if not kind or r["kind"] == kind]
    judge = load_judge(folder)
    for r in rows:
        j = judge.get((r["task"], r["arm"], r["rep"]))
        r["judge"] = j["score"] if j and j.get("score") is not None else None
    ra = {(r["task"], r["rep"]): r for r in rows if r["arm"] == a and not r.get("error")}
    rb = {(r["task"], r["rep"]): r for r in rows if r["arm"] == b and not r.get("error")}
    keys = sorted(set(ra) & set(rb))
    out = [f"A={a} n={len(ra)}  B={b} n={len(rb)}  paired={len(keys)}  kind={kind or 'all'}  (runs with an endpoint error left out)",
           f"{'metric':17s} {'A mean':>10s} {'B mean':>10s} {'B-A':>10s} {'95% CI':>22s}  wins/losses  n"]
    for key in ("score", "judge", "cost_usd", "turns", "tool_calls", "search_calls", "read_calls", "prompt_tokens",
                "cached_tokens", "completion_tokens", "search_chars", "tool_chars", "truncated", "duration_s"):
        pairs = [(ra[k][key], rb[k][key]) for k in keys
                 if isinstance(ra[k].get(key), (int, float)) and isinstance(rb[k].get(key), (int, float))]
        if not pairs:
            continue
        d = [y - x for x, y in pairs]
        lo, hi = ci(d)
        w, l = sum(1 for v in d if v > 0), sum(1 for v in d if v < 0)
        out.append(f"{key:17s} {statistics.mean([x for x, _ in pairs]):10.3f} {statistics.mean([y for _, y in pairs]):10.3f} "
                   f"{statistics.mean(d):+10.3f} [{lo:+9.3f}, {hi:+9.3f}]  {w}/{l}  {len(d)}")
    return "\n".join(out)


def run_judge(folder: Path, model: str, jobs: int = 4) -> None:
    """Score the SWE-QA answers blind to the arm with scripts/judge.py's
    prompt, through the REPL's endpoint under `model` (a provider/model spec)."""
    import judge as judge_mod
    from silica_core import repl
    from silica_core.config import CONFIG

    CONFIG.model = model
    refs = {r["task_id"]: r["reference_answer"]
            for r in json.loads((REPO / "bench" / "swe-qa" / "references.json").read_text())["references"]}
    questions = {t["task_id"]: t["question"] for t in json.loads((REPO / "bench" / "swe-qa" / "tasks.json").read_text())}
    done = load_judge(folder)
    todo = [r for r in load(folder) if r["kind"] == "swe" and (r["task"], r["arm"], r["rep"]) not in done
            and r["task"] in refs and not r.get("error")]
    lock = threading.Lock()

    def score_one(r: dict) -> None:
        calls: list[dict] = []
        prompt = judge_mod.PROMPT.format(question=questions[r["task"]], reference=refs[r["task"]],
                                         answer=r["answer"] or "(no answer)")
        try:
            msg = repl.complete([{"role": "user", "content": prompt}], [], lambda s: None, post=usage_post(calls))
            text = msg.get("content") or ""
            verdict = json.loads(text[text.find("{"):text.rfind("}") + 1])
            row = {"score": int(verdict["score"]), "missing": verdict.get("missing", []), "wrong": verdict.get("wrong", [])}
        except Exception as e:  # the judge's failure is a None score, not a crash of the pass
            row = {"score": None, "error": f"{type(e).__name__}: {e}"[:300]}
        row = {"task": r["task"], "arm": r["arm"], "rep": r["rep"], "judge": model,
               "cost_usd": round(sum(c.get("cost", 0) or 0 for c in calls), 6), **row}
        with lock:
            with (folder / "judge.jsonl").open("a") as fh:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            print(f"{r['task']:14s} {r['arm']:5s} rep{r['rep']}: {row.get('score')} {row.get('error', '')}", flush=True)

    with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as ex:
        list(ex.map(score_one, todo))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--arms", default="base,lean,wide")
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--jobs", type=int, default=6)
    ap.add_argument("--set", default="base,hard,swe", help="comma-separated task sets")
    ap.add_argument("--tasks", default="", help="comma-separated ids; empty = all")
    ap.add_argument("--timeout", type=int, default=900, help="seconds per run")
    ap.add_argument("--out", default="", help="results folder; default docs/baseline/<stamp>-repl")
    ap.add_argument("--prepare", action="store_true", help="warm every task root (index and vectors) first, one at a time")
    ap.add_argument("--summary", default="", help="only summarise this results folder")
    ap.add_argument("--compare", nargs=3, metavar=("ARM_A", "ARM_B", "FOLDER"), help="paired comparison of two arms")
    ap.add_argument("--kind", default="", help="with --compare: only this task kind (code, docs, hard, swe)")
    ap.add_argument("--judge", default="", help="score the SWE-QA answers of this folder")
    ap.add_argument("--judge-model", default="openrouter/deepseek/deepseek-v4-pro")
    ap.add_argument("--one", nargs=3, metavar=("TASK", "ARM", "REP"), help=argparse.SUPPRESS)
    ap.add_argument("--warm-only", action="store_true", help=argparse.SUPPRESS)
    a = ap.parse_args()

    if a.warm_only:
        print(json.dumps(warm()))
        return 0
    if a.one:
        task = next(t for t in ALL_TASKS if t["id"] == a.one[0])
        print(json.dumps(one(task, a.one[1], int(a.one[2]), Path(a.out)), ensure_ascii=False))
        return 0
    if a.summary:
        print(summarize(Path(a.summary)))
        return 0
    if a.compare:
        print(compare(Path(a.compare[2]), a.compare[0], a.compare[1], a.kind))
        return 0
    if a.judge:
        run_judge(Path(a.judge), a.judge_model, a.jobs)
        print(summarize(Path(a.judge)))
        return 0

    from silica_core.config import CONFIG
    if not CONFIG.model:
        print("SILICA_MODEL is unset (see silica-core repl)", file=sys.stderr)
        return 1
    arms = a.arms.split(",")
    for arm in arms:
        if arm not in ARMS:
            print(f"unknown arm {arm}; arms: {', '.join(ARMS)}", file=sys.stderr)
            return 2
    pool = {"base": baseline.TASKS, "hard": baseline.HARD_TASKS, "swe": baseline.SWE_TASKS}
    wanted = [t for s in a.set.split(",") for t in pool[s] if not a.tasks or t["id"] in a.tasks.split(",")]
    # absolute: a child runs in the task's folder, where a relative --out would not resolve
    out = (Path(a.out) if a.out else REPO / "docs" / "baseline" / (time.strftime("%Y-%m-%d-%H%M") + "-repl")).resolve()
    out.mkdir(parents=True, exist_ok=True)
    runs = out / "runs.jsonl"
    done = {(r["task"], r["arm"], r["rep"]) for r in load(out) if not r.get("error")}
    grid = [(t, arm, rep) for t in wanted for rep in range(1, a.reps + 1) for arm in arms
            if (t["id"], arm, rep) not in done]
    print(f"{len(grid)} runs -> {runs}  (model {CONFIG.model}, jobs {a.jobs})", flush=True)
    if a.prepare:
        prep = {}
        for cwd in sorted({str(t["cwd"]) for t in wanted}):
            p = subprocess.run([sys.executable, __file__, "--warm-only"], cwd=cwd,
                               env={**os.environ, **ENV, "SILICA_VAULT": cwd}, capture_output=True, text=True)
            try:
                prep[cwd] = json.loads(p.stdout.strip().splitlines()[-1])
            except (ValueError, IndexError):
                prep[cwd] = {"state": "crash", "hint": p.stderr[-300:]}
            print(f"prepared {cwd}: {prep[cwd]}", flush=True)
        (out / "prepare.json").write_text(json.dumps(prep, indent=1))
    if grid:
        m = {"started": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "model": CONFIG.model,
             "runner": {"path": Path(__file__).resolve().relative_to(REPO).as_posix(),
                        "sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                        "repo": baseline.identity(REPO)},
             "args": {k: v for k, v in vars(a).items() if not isinstance(v, Path)}, "arms": {k: ARMS[k] for k in arms},
             "tools": TOOLS, "env": ENV, "result_cap": RESULT_CAP, "preamble": baseline.PREAMBLE,
             "corpora": {str(c): baseline.identity(Path(c)) for c in sorted({str(t["cwd"]) for t in wanted})},
             "tasks": [{k: (str(v) if isinstance(v, Path) else v) for k, v in t.items()} for t in wanted]}
        with (out / "manifest.jsonl").open("a") as fh:
            fh.write(json.dumps(m, ensure_ascii=False) + "\n")
    lock = threading.Lock()

    def job(t, arm, rep):
        r = spawn(t, arm, rep, out, a.timeout)
        with lock:
            with runs.open("a") as fh:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
            print(f"{r['task']} {arm} rep{rep}: score={r.get('score')} cost={r.get('cost_usd')} turns={r.get('turns')} "
                  f"search={r.get('search_calls')} read={r.get('read_calls')} tok={r.get('prompt_tokens')} "
                  f"{r.get('duration_s')}s {r.get('error', '')[:80]}", flush=True)

    with concurrent.futures.ThreadPoolExecutor(max_workers=a.jobs) as ex:
        list(ex.map(lambda g: job(*g), grid))
    (out / "summary.md").write_text(summarize(out) + "\n")
    print(summarize(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
