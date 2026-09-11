#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Alessandro Carosia

"""Paired comparison of two scripts/baseline.py folders that ran the same tasks
and reps under one difference (a description, a hook, a guidance file):

    scripts/ab.py docs/baseline/<A> docs/baseline/<B>

Pairs by (task, rep), reports B minus A with a 95% bootstrap interval on the
mean and the wins/losses, on uptake (runs with at least one silica_search),
calls, turns, cost, tokens, seconds and the judge when judge.jsonl exists."""
import json, random, statistics, sys
from pathlib import Path

SEARCH = "mcp__plugin_silica-core_silica-core__silica_search"
READ = "mcp__plugin_silica-core_silica-core__silica_read"

def load(folder):
    runs = {}
    for l in (Path(folder) / "runs.jsonl").read_text().splitlines():
        if not l.strip(): continue
        r = json.loads(l)
        if r.get("subtype") == "limit": continue
        runs[(r["task"], r["rep"])] = r
    judge = {}
    jp = Path(folder) / "judge.jsonl"
    if jp.exists():
        for l in jp.read_text().splitlines():
            if l.strip():
                j = json.loads(l)
                if j.get("score") is not None:
                    judge[(j["task"], j["rep"])] = j["score"]
    return runs, judge

def ci(diffs, n=10000, seed=0):
    rnd = random.Random(seed)
    means = sorted(statistics.mean(rnd.choices(diffs, k=len(diffs))) for _ in range(n))
    return means[int(0.025 * n)], means[int(0.975 * n)]

def metric(r, key):
    if key == "uptake": return 1 if r["tools"].get(SEARCH) else 0
    if key == "search_calls": return r["tools"].get(SEARCH, 0)
    if key == "read_calls": return r["tools"].get(READ, 0)
    if key == "context_tok": return (r.get("input_tokens") or 0) + (r.get("cache_read") or 0) + (r.get("cache_write") or 0)
    return r.get(key)

a_runs, a_judge = load(sys.argv[1]); b_runs, b_judge = load(sys.argv[2])
keys = sorted(set(a_runs) & set(b_runs))
print(f"A={sys.argv[1]} n={len(a_runs)}  B={sys.argv[2]} n={len(b_runs)}  paired={len(keys)}")
print(f"{'metric':14s} {'A mean':>9s} {'B mean':>9s} {'B-A':>9s} {'95% CI':>20s}  wins/losses")
for key in ("uptake", "search_calls", "read_calls", "turns", "tool_calls", "cost_usd", "duration_s", "context_tok", "output_tokens"):
    a = [metric(a_runs[k], key) for k in keys]; b = [metric(b_runs[k], key) for k in keys]
    if any(v is None for v in a + b): continue
    d = [y - x for x, y in zip(a, b)]
    lo, hi = ci(d)
    w, l = sum(1 for v in d if v > 0), sum(1 for v in d if v < 0)
    print(f"{key:14s} {statistics.mean(a):9.3f} {statistics.mean(b):9.3f} {statistics.mean(d):+9.3f} [{lo:+8.3f}, {hi:+8.3f}]  {w}/{l}")
jk = [k for k in keys if k in a_judge and k in b_judge]
if jk:
    d = [b_judge[k] - a_judge[k] for k in jk]; lo, hi = ci(d)
    print(f"{'judge':14s} {statistics.mean([a_judge[k] for k in jk]):9.1f} {statistics.mean([b_judge[k] for k in jk]):9.1f} {statistics.mean(d):+9.1f} [{lo:+8.1f}, {hi:+8.1f}]  {sum(1 for v in d if v>0)}/{sum(1 for v in d if v<0)}  (n={len(jk)})")
# per task uptake
print("\nper task: search calls A | B over reps, judge A | B")
tasks = sorted({k[0] for k in keys})
for t in tasks:
    ra = [metric(a_runs[k], "search_calls") for k in keys if k[0] == t]
    rb = [metric(b_runs[k], "search_calls") for k in keys if k[0] == t]
    ja = [a_judge[k] for k in keys if k[0] == t and k in a_judge]; jb = [b_judge[k] for k in keys if k[0] == t and k in b_judge]
    print(f"  {t:15s} {ra} | {rb}   {ja} | {jb}")
