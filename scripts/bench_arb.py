#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Alessandro Carosia

"""Agent Retrieval Bench (ARB) through `silica_search`: MRR, Recall@20 and
canonical BCY@8k over the 345 positive samples of the v2 release, the numbers
its README publishes for Qwen3-Embedding, RepoMap, nomic, jina, its own
lexical heuristic and BM25.

ARB ships each repository as one `*.chunks.jsonl` at a frozen base commit;
the `kind=file` rows carry the canonical file text every published method was
ranked over. This script writes those rows back out as a folder, indexes it
the way the plugin does (`index_code`, potion for the dense leg), asks
`core.search` one question per sample and keeps the ranked file list. Metrics
come from ARB's own `sample_metrics` / `summarize_details`, so a run lands in
the same `details.jsonl` + `summary.json` shape as `arb eval-baseline` and
`arb report-bcy-curve` scores it beside the released baselines.

    scripts/bench_arb.py --arm lexical            # BM25 + path/symbol units, no vectors
    scripts/bench_arb.py --arm hybrid             # + potion-retrieval-32M, the plugin's default
    scripts/bench_arb.py --arm hybrid --k 40      # a wider pool: k*POOL_FACTOR units scored
    scripts/bench_arb.py --baselines              # rerun ARB's lexical/bm25/repomap here
    scripts/bench_arb.py --report                 # the table, from whatever ran

`--data` is the folder `arb download-benchmark --all --local-dir data` wrote;
snapshots are materialised once under `<data>/materialised/` and reused, and
every index lives beside them, never inside the corpus a search walks.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
BENCH = ROOT / "bench" / "arb"
POTION = "model2vec/minishlab/potion-retrieval-32M"
SUBSETS = ("v2_code2test", "v2_comment2context", "v2_trace2code", "v2_edit2ripple")
# The README leaderboard over the same 345 positive samples, for the report.
PUBLISHED = [
    ("Qwen3-Embedding-4B", "embedding", 0.6306, 0.2379, 0.3409),
    ("Qwen3-Embedding-8B", "embedding", 0.7029, 0.2336, 0.3732),
    ("pplx-embed-v1-4b", "embedding", 0.6072, 0.2267, 0.3549),
    ("RepoMap", "structure", 0.6333, 0.2158, 0.3788),
    ("nomic-embed-code", "embedding", 0.5244, 0.1986, 0.2781),
    ("jina-code-embeddings-0.5b", "embedding", 0.4823, 0.1914, 0.2783),
    ("Lexical", "lexical", 0.4940, 0.1574, 0.2650),
    ("BM25", "lexical", 0.4452, 0.1520, 0.2051),
]


def arb_src(data: Path) -> Path:
    """ARB's own package, imported rather than installed: it has no deps."""
    for cand in (Path(os.environ.get("ARB_REPO", "")), data.parent / "agent-retrieval-bench"):
        if (cand / "src" / "agent_retrieval_bench").is_dir():
            return cand / "src"
    sys.exit("set ARB_REPO to the agent-retrieval-bench checkout")


# ---------------------------------------------------------------------------
# corpus
# ---------------------------------------------------------------------------

def materialise(chunks_path: Path, dest: Path) -> dict[str, str]:
    """The snapshot as files, and `rel -> text` for the metrics. ARB truncates
    long files when it builds the corpus; what is written here is what every
    published method ranked, so the comparison stays on one corpus."""
    texts: dict[str, str] = {}
    with chunks_path.open(encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            if row.get("kind") != "file":
                continue
            rel = str(row.get("path") or "")
            if not rel or rel.startswith("/") or ".." in rel.split("/"):
                continue
            texts[rel] = row.get("text") or ""
    marker = dest / ".arb_files"
    if marker.is_file() and marker.read_text(encoding="utf-8").strip() == str(len(texts)):
        return texts
    shutil.rmtree(dest, ignore_errors=True)
    for rel, text in texts.items():
        full = dest / rel
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(text, encoding="utf-8", errors="replace")
    dest.mkdir(parents=True, exist_ok=True)
    marker.write_text(str(len(texts)), encoding="utf-8")
    return texts


# ---------------------------------------------------------------------------
# the arm
# ---------------------------------------------------------------------------

QUARANTINE = BENCH / "quarantine.txt"


def _quarantined() -> set[str]:
    if not QUARANTINE.is_file():
        return set()
    return {line for line in QUARANTINE.read_text(encoding="utf-8").splitlines() if line.strip()}


def silica_rank(root: Path, index_dir: Path, queries: list[str], *, hybrid: bool,
                k: int, pool_factor: int, marker: Path | None = None) -> tuple[list[list[str]], dict]:
    """One index over the snapshot, then one `core.search` per sample; the
    ranking is the hit list at `per_doc=1`, which is one file per hit and so
    the ranked file list ARB scores."""
    from silica_core.config import CONFIG
    from silica_core.kernel.code import codeunits
    from silica_core.kernel.recall import lexical, paths
    import silica_core.core as core

    # tree-sitter segfaults the process on some real files (fastapi's
    # tests/test_dependency_wrapped.py at this base commit, reproduced with
    # tree_sitter_language_pack alone and no silica in the picture). The path
    # under the parser is written down before each parse, so the parent can
    # quarantine it and the next attempt reads that file as line windows.
    banned = _quarantined()
    real_language_for = codeunits.language_for
    if marker is not None:
        handle = marker.open("w", encoding="utf-8")

        def watched(rel: str):
            handle.seek(0)
            handle.write(rel + "\n")
            handle.truncate()
            handle.flush()
            return None if rel in banned else real_language_for(rel)

        codeunits.language_for = watched  # type: ignore[assignment]

    CONFIG.vault_path = str(root)
    CONFIG.index_code = True
    CONFIG.embedding_base_url = ""
    CONFIG.embedding_model = POTION if hybrid else ""
    core.POOL_FACTOR = pool_factor
    paths.index_dir_for = lambda vault, _d=index_dir: _d  # type: ignore[assignment]
    lexical._STORE_CACHE.clear()
    core._section_cache.clear()
    t0 = time.time()
    built = core.build_index(embed=hybrid)
    if "error" in built:
        sys.exit(f"index: {built['error']}")
    t_index = time.time() - t0
    ranked, t_q = [], 0.0
    info: dict = {"docs": built.get("docs"), "index_s": round(t_index, 1)}
    for query in queries:
        t1 = time.time()
        r = core.search(query, k=k, per_doc=1)
        t_q += time.time() - t1
        if "error" in r:
            sys.exit(f"search: {r['error']}")
        seen: list[str] = []
        for hit in r["hits"]:
            if hit["path"] not in seen:
                seen.append(hit["path"])
        ranked.append(seen)
        info["dense"] = r["dense"].get("state")
    info["query_ms"] = round(1000 * t_q / max(len(queries), 1), 1)
    info["quarantined"] = len(banned)
    return ranked, info


def rank_isolated(root: Path, index_dir: Path, queries: list[str], *, hybrid: bool,
                  k: int, pool_factor: int, scratch: Path) -> tuple[list[list[str]], dict]:
    """`silica_rank` in a child process. A parser that takes the process down
    costs one snapshot's attempt and one line in `quarantine.txt`, not the run."""
    cfg, out, marker = scratch / "cfg.json", scratch / "out.json", scratch / "parsing.txt"
    cfg.write_text(json.dumps({"root": str(root), "index_dir": str(index_dir), "queries": queries,
                               "hybrid": hybrid, "k": k, "pool_factor": pool_factor,
                               "marker": str(marker), "out": str(out)}), encoding="utf-8")
    for attempt in range(6):
        out.unlink(missing_ok=True)
        rc = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--child", str(cfg)]).returncode
        if rc == 0 and out.is_file():
            payload = json.loads(out.read_text(encoding="utf-8"))
            return payload["ranked"], payload["info"]
        bad = marker.read_text(encoding="utf-8").strip() if marker.is_file() else ""
        if not bad or bad in _quarantined():
            sys.exit(f"child failed (rc={rc}) with nothing new to quarantine (last parse: {bad!r})")
        QUARANTINE.parent.mkdir(parents=True, exist_ok=True)
        with QUARANTINE.open("a", encoding="utf-8") as handle:
            handle.write(bad + "\n")
        print(f"  quarantined after rc={rc}: {bad} (attempt {attempt + 1})", flush=True)
    sys.exit("too many parser crashes on one snapshot")


def child(cfg_path: Path) -> None:
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    ranked, info = silica_rank(Path(cfg["root"]), Path(cfg["index_dir"]), cfg["queries"],
                               hybrid=cfg["hybrid"], k=cfg["k"], pool_factor=cfg["pool_factor"],
                               marker=Path(cfg["marker"]))
    Path(cfg["out"]).write_text(json.dumps({"ranked": ranked, "info": info}), encoding="utf-8")


def run_arm(data: Path, arm: str, *, k: int, pool_factor: int, limit: int | None,
            subsets: tuple[str, ...]) -> dict:
    sys.path.insert(0, str(arb_src(data)))
    from agent_retrieval_bench.baseline import (
        gold_blocks, gold_spans, hard_negative_files, iter_samples, query_has_leakage,
        query_provenance, query_text_for_eval, sample_metrics, summarize_details,
        target_gold_files, unique_ranked_paths,
    )
    from agent_retrieval_bench.io import read_jsonl

    work = data / "materialised"
    idx_root = data / "silica-index"
    idx_root.mkdir(parents=True, exist_ok=True)
    started = time.time()
    pending: dict[Path, list[dict]] = {}
    skipped: dict[str, int] = {}
    for subset in subsets:
        manifest = {}
        for row in read_jsonl(data / "corpus" / subset / "corpus_manifest.jsonl"):
            if row.get("status") == "ok":
                # `chunks_path` is written relative to the download's parent
                manifest[(row["repo"], row["base_commit"])] = data / str(row["chunks_path"]).split("data/", 1)[-1]
        for sample in iter_samples([data / "benchmark" / subset / "samples.jsonl"]):
            gold = target_gold_files(sample)
            if not gold:
                skipped["no_gold"] = skipped.get("no_gold", 0) + 1
                continue
            query = query_text_for_eval(sample)
            if query_has_leakage(sample, query):
                skipped["query_leakage"] = skipped.get("query_leakage", 0) + 1
                continue
            chunks = manifest.get((sample.get("repo"), sample.get("base_commit")))
            if not chunks or not chunks.is_file():
                skipped["missing_corpus"] = skipped.get("missing_corpus", 0) + 1
                continue
            pending.setdefault(chunks, []).append({"sample": sample, "gold": gold, "query": query})
    if limit:
        flat = [(c, s) for c, rows in pending.items() for s in rows][:limit]
        pending = {}
        for c, s in flat:
            pending.setdefault(c, []).append(s)

    label = f"silica-{arm}" + (f"-k{k}" if k != 20 else "") + (f"-pool{pool_factor}" if pool_factor != 3 else "")
    BENCH.mkdir(parents=True, exist_ok=True)
    shard = BENCH / f"{label}_details.jsonl"
    # tree-sitter is native and has taken the process down mid-run (a general
    # protection fault on one snapshot out of hundreds): every snapshot's rows
    # are appended as they are produced and a rerun resumes from them.
    details: list[dict] = [json.loads(line) for line in shard.read_text(encoding="utf-8").splitlines()
                           if line.strip()] if shard.is_file() else []
    done = {d["sample_id"] for d in details}
    infos: list[dict] = []
    total = sum(len(v) for v in pending.values())
    handle = shard.open("a", encoding="utf-8")
    for n, (chunks, rows) in enumerate(sorted(pending.items()), start=1):
        commit = chunks.stem.split(".")[0]
        repo = rows[0]["sample"]["repo"].replace("/", "__")
        rows = [r for r in rows if r["sample"].get("id") not in done]
        if not rows:
            continue
        dest, index_dir = work / repo / commit, idx_root / repo / commit
        texts = materialise(chunks, dest)
        print(f"[{n}/{len(pending)}] {repo}@{commit[:8]} files={len(texts)} indexing…", flush=True)
        ranked, info = rank_isolated(dest, index_dir, [r["query"] for r in rows],
                                     hybrid=arm == "hybrid", k=k, pool_factor=pool_factor,
                                     scratch=idx_root)
        infos.append(info)
        print(f"[{n}/{len(pending)}] {repo}@{commit[:8]} files={len(texts)} "
              f"docs={info['docs']} index={info['index_s']}s q={info['query_ms']}ms "
              f"samples={len(rows)} done={len(details) + len(rows)}/{total}", flush=True)
        for row, paths_ranked in zip(rows, ranked):
            sample, gold = row["sample"], row["gold"]
            chunk_rank = [{"path": p, "kind": "file", "symbol": "", "text": texts.get(p, "")}
                          for p in paths_ranked]
            negatives = hard_negative_files(sample)
            detail = {
                "sample_id": sample.get("id"), "task_type": sample.get("task_type"),
                "repo": sample.get("repo"), "base_commit": sample.get("base_commit"),
                "candidate_filter": "all_files", "ranker": f"silica-{arm}",
                "gold_files": gold, "gold_spans": gold_spans(sample), "gold_blocks": gold_blocks(sample),
                "hard_negative_files": negatives, "query_provenance": query_provenance(sample),
                "gold_ranks": {p: (paths_ranked.index(p) + 1 if p in paths_ranked else None) for p in gold},
                "top_files": unique_ranked_paths(chunk_rank)[:20],
                "metrics": sample_metrics(gold, chunk_rank, hard_negative_files=negatives),
            }
            details.append(detail)
            handle.write(json.dumps(detail, ensure_ascii=False, sort_keys=True) + "\n")
        handle.flush()
    handle.close()

    result = {
        "mode": "corpus", "ranker": label, "candidate_filter": "all_files",
        "arm": arm, "k": k, "pool_factor": pool_factor,
        "evaluated": len(details), "skipped": skipped, "metrics": summarize_details(details),
        "runtime": {"wall_time_seconds": round(time.time() - started, 1),
                    "index_s": round(sum(i["index_s"] for i in infos), 1),
                    "query_ms": round(sum(i["query_ms"] for i in infos) / max(len(infos), 1), 1),
                    "dense": infos[0].get("dense") if infos else None},
    }
    (BENCH / f"{label}_summary.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


# ---------------------------------------------------------------------------
# baselines and report
# ---------------------------------------------------------------------------

def run_baselines(data: Path, subsets: tuple[str, ...]) -> None:
    """ARB's own evaluators on this machine, so the published rows have a
    same-corpus twin: `arb eval-baseline` writes the details the report reads."""
    arb = arb_src(data).parent / ".venv" / "bin" / "arb"
    cwd = data.parent / "arbrun"
    cwd.mkdir(exist_ok=True)
    link = cwd / "data"
    if not link.exists():
        link.symlink_to(data)
    BENCH.mkdir(parents=True, exist_ok=True)
    for subset in subsets:
        for ranker in ("lexical", "bm25", "repomap"):
            out = BENCH / f"arb-{ranker}_{subset}"
            if out.with_suffix(".jsonl").is_file():
                continue
            cmd = [str(arb), "eval-repomap" if ranker == "repomap" else "eval-baseline",
                   "--derived", f"data/benchmark/{subset}", "--corpus", f"data/corpus/{subset}",
                   "--candidate-filter", "all_files", "--no-keep-list",
                   "--out", str(out.with_suffix(".json")), "--details", str(out.with_suffix(".jsonl"))]
            if ranker != "repomap":
                cmd += ["--ranker", ranker]
            print(f"baseline {ranker} {subset}", flush=True)
            subprocess.run(cmd, cwd=cwd, check=True, stdout=subprocess.DEVNULL)


def bcy(data: Path, runs: list[tuple[str, str, Path]]) -> dict[str, float]:
    """Canonical BCY@8k: ARB repacks each run's stored top-20 file list from
    the corpus text, so every row in the report is packed the same way."""
    sys.path.insert(0, str(arb_src(data)))
    from agent_retrieval_bench.bcy_curve import report_bcy_budget_curve
    manifest = data / "corpus" / "merged_corpus_manifest.jsonl"
    if not manifest.is_file():
        rows, seen = [], set()
        for subset in SUBSETS:
            for line in (data / "corpus" / subset / "corpus_manifest.jsonl").read_text(encoding="utf-8").splitlines():
                row = json.loads(line)
                key = (row.get("repo"), row.get("base_commit"))
                if key in seen or row.get("status") != "ok":
                    continue
                seen.add(key)
                row["chunks_path"] = str(data / str(row["chunks_path"]).split("data/", 1)[-1])
                rows.append(json.dumps(row))
        manifest.write_text("\n".join(rows) + "\n", encoding="utf-8")
    report = report_bcy_budget_curve(corpus_manifest_path=manifest, out_path=BENCH / "bcy.json",
                                     markdown_out_path=BENCH / "bcy.md", runs=runs)
    return {run["label"]: run["overall"]["BCY@8000"] for run in report["runs"]}


def report(data: Path) -> None:
    sys.path.insert(0, str(arb_src(data)))
    from agent_retrieval_bench.baseline import summarize_details
    from agent_retrieval_bench.io import read_jsonl

    runs: list[tuple[str, str, Path]] = []
    rows = []
    merged: dict[str, list[dict]] = {}
    for path in sorted(BENCH.glob("*.jsonl")):
        if "_merged_details" in path.name:
            continue
        label = path.stem[: -len("_details")] if path.stem.endswith("_details") else path.stem
        base = label.rsplit("_v2_", 1)[0] if "_v2_" in label else label
        merged.setdefault(base, []).extend(read_jsonl(path))
    for label, details in merged.items():
        path = BENCH / f"{label}_merged_details.jsonl"
        path.write_text("".join(json.dumps(d, sort_keys=True) + "\n" for d in details), encoding="utf-8")
        runs.append((label, "silica" if label.startswith("silica") else "arb", path))
        summary = summarize_details(details)
        rows.append((label, summary))
    points = bcy(data, runs)
    print(f"\n{'method':34s} {'n':>4s} {'R@5':>7s} {'R@10':>7s} {'R@20':>7s} {'MRR':>7s} {'BCY@8k':>7s}")
    for label, summary in sorted(rows, key=lambda r: -r[1]["overall"]["MRR"]):
        o = summary["overall"]
        b = points.get(label)
        print(f"{label:34s} {o['samples']:4d} {o['Recall@5']:7.4f} {o['Recall@10']:7.4f} "
              f"{o['Recall@20']:7.4f} {o['MRR']:7.4f} {(f'{b:.4f}' if b is not None else '—'):>7s}")
    print("\npublished (ARB leaderboard, same 345 samples):")
    for name, family, r20, mrr, b8 in PUBLISHED:
        print(f"{name:34s} {345:4d} {'':7s} {'':7s} {r20:7.4f} {mrr:7.4f} {b8:7.4f}  [{family}]")
    for task in ("code2test", "comment2context", "trace2code", "edit2ripple"):
        print(f"\n{task}")
        for label, summary in sorted(rows, key=lambda r: -r[1].get(task, {}).get("MRR", 0)):
            o = summary.get(task)
            if not o:
                continue
            print(f"  {label:32s} {o['samples']:4d} {o['Recall@5']:7.4f} {o['Recall@10']:7.4f} "
                  f"{o['Recall@20']:7.4f} {o['MRR']:7.4f}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", type=Path, default=Path.home() / ".cache" / "arb-data")
    ap.add_argument("--arm", choices=("lexical", "hybrid"))
    ap.add_argument("--k", type=int, default=20)
    ap.add_argument("--pool-factor", type=int, default=3)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--subset", action="append", choices=SUBSETS)
    ap.add_argument("--baselines", action="store_true")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--child", type=Path, help=argparse.SUPPRESS)
    args = ap.parse_args()
    if args.child:
        child(args.child)
        return
    subsets = tuple(args.subset) if args.subset else SUBSETS
    if args.baselines:
        run_baselines(args.data, subsets)
    if args.arm:
        result = run_arm(args.data, args.arm, k=args.k, pool_factor=args.pool_factor,
                         limit=args.limit, subsets=subsets)
        print(json.dumps({k: v for k, v in result.items() if k != "metrics"}, indent=2))
        print(json.dumps(result["metrics"]["overall"], indent=2))
    if args.report:
        report(args.data)


if __name__ == "__main__":
    main()
