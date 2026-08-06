#!/usr/bin/env python3
"""Analyze scoring variance across multiple independent pipeline runs.

Reads run data from wiki/variance-data/run-{01..10}/ and writes a
consolidated report to wiki/22-variance-experiment.md.
"""

import json
import os
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from statistics import mean, stdev

sys.path.insert(0, os.path.dirname(__file__))
from artifact_utils import read_frontmatter

RESULTS_DIR = Path(__file__).resolve().parent.parent.parent / "wiki" / "variance-data"
REPORT_PATH = Path(__file__).resolve().parent.parent.parent / "wiki" / "22-variance-experiment.md"

DIMENSIONS = ["feasibility", "testability", "scope", "architecture"]


def load_runs(results_dir):
    """Load all run data, keyed by source_rfe for stability."""
    strategies = defaultdict(lambda: {"title": "", "runs": []})
    run_metas = []

    for run_dir in sorted(results_dir.glob("run-*")):
        meta_path = run_dir / "meta.json"
        if not meta_path.exists():
            continue

        with open(meta_path) as f:
            meta = json.load(f)

        run_metas.append(meta)

        if meta.get("status") not in ("complete",):
            continue

        arts = run_dir / "artifacts"
        tasks_dir = arts / "strat-tasks"
        reviews_dir = arts / "strat-reviews"

        if not tasks_dir.exists() or not reviews_dir.exists():
            continue

        # Build strat_id → source_rfe mapping from task frontmatter
        id_map = {}
        titles = {}
        for task_file in tasks_dir.glob("*.md"):
            fm, _ = read_frontmatter(str(task_file))
            strat_id = fm.get("strat_id", task_file.stem)
            source_rfe = fm.get("source_rfe", strat_id)
            id_map[strat_id] = source_rfe
            titles[source_rfe] = fm.get("title", "")

        # Parse review files
        for review_file in reviews_dir.glob("*-review.md"):
            if "-review-comment" in review_file.name:
                continue
            fm, _ = read_frontmatter(str(review_file))
            strat_id = fm.get("strat_id", review_file.stem.replace("-review", ""))
            source_rfe = id_map.get(strat_id, strat_id)

            scores = fm.get("scores", {})
            reviewers = fm.get("reviewers", {})

            run_data = {
                "run": meta["run"],
                "strat_id": strat_id,
                "recommendation": fm.get("recommendation", ""),
                "total": scores.get("total"),
                "reviewers": {},
            }
            for dim in DIMENSIONS:
                run_data[dim] = scores.get(dim)
                run_data["reviewers"][dim] = reviewers.get(dim, "")

            strategies[source_rfe]["runs"].append(run_data)
            if titles.get(source_rfe):
                strategies[source_rfe]["title"] = titles[source_rfe]

    return dict(strategies), run_metas


def safe_stats(values):
    """Compute mean, stdev, min, max for a list of numeric values."""
    clean = [v for v in values if v is not None]
    if not clean:
        return {"mean": None, "sd": None, "min": None, "max": None, "n": 0}
    m = mean(clean)
    sd = stdev(clean) if len(clean) > 1 else 0.0
    return {"mean": m, "sd": sd, "min": min(clean), "max": max(clean), "n": len(clean)}


def verdict_label(rec):
    """Normalize recommendation to APPROVE/REVISE/REJECT."""
    if not rec:
        return "UNKNOWN"
    r = rec.strip().upper()
    if "APPROVE" in r:
        return "APPROVE"
    if "REVISE" in r:
        return "REVISE"
    if "REJECT" in r:
        return "REJECT"
    return r


def generate_report(strategies, run_metas):
    """Generate the full markdown report."""
    total_runs = len(run_metas)
    complete_runs = sum(1 for m in run_metas if m.get("status") == "complete")
    failed_runs = total_runs - complete_runs

    lines = []
    lines.append("# Scoring Variance Experiment")
    lines.append("")
    lines.append(f"*Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}*")
    lines.append("")

    # --- Executive Summary ---
    all_totals = []
    all_verdicts = defaultdict(list)
    for rfe, data in strategies.items():
        for run in data["runs"]:
            if run["total"] is not None:
                all_totals.append(run["total"])
            all_verdicts[rfe].append(verdict_label(run["recommendation"]))

    consistency_pcts = []
    for rfe, verdicts in all_verdicts.items():
        if verdicts:
            most_common = max(set(verdicts), key=verdicts.count)
            consistency_pcts.append(verdicts.count(most_common) / len(verdicts) * 100)

    avg_consistency = mean(consistency_pcts) if consistency_pcts else 0
    total_stats = safe_stats(all_totals)

    lines.append("## Executive Summary")
    lines.append("")
    lines.append(
        f"Across {complete_runs} independent runs of {len(strategies)} strategies, "
        f"the average total score was **{total_stats['mean']:.1f}/8** "
        f"(sd={total_stats['sd']:.2f}, range {total_stats['min']}-{total_stats['max']}). "
        f"Verdict consistency averaged **{avg_consistency:.0f}%** — "
        f"the same strategy received the same verdict in {avg_consistency:.0f}% of runs on average."
    )
    lines.append("")

    # --- Methodology ---
    lines.append("## Methodology")
    lines.append("")
    lines.append("- **Batch**: batch-01 (10 RFE IDs, 4 pass label gate)")
    lines.append("- **Model**: claude-opus-4-6")
    lines.append("- **Mode**: dry-run (no Jira writes)")
    lines.append(f"- **Runs**: {total_runs} independent runs ({complete_runs} complete, {failed_runs} failed)")
    lines.append("- **Pipeline**: strategy.create → strategy.refine → strategy.review")
    lines.append("- **Scoring**: 4 dimensions (feasibility, testability, scope, architecture), each 0-2, total 0-8")
    lines.append("- **Verdicts**: APPROVE (≥6, no zeros), REVISE (≥3, ≤1 zero), REJECT (<3 or 2+ zeros)")
    lines.append("")

    # --- Per-Strategy Score Tables ---
    lines.append("## Per-Strategy Score Tables")
    lines.append("")

    for rfe in sorted(strategies.keys()):
        data = strategies[rfe]
        title = data["title"] or rfe
        runs = sorted(data["runs"], key=lambda r: r["run"])

        lines.append(f"### {rfe} — {title}")
        lines.append("")
        lines.append("| Run | F | T | S | A | Total | Verdict |")
        lines.append("|-----|---|---|---|---|-------|---------|")

        for run in runs:
            f = run.get("feasibility", "—")
            t = run.get("testability", "—")
            s = run.get("scope", "—")
            a = run.get("architecture", "—")
            total = run.get("total", "—")
            verdict = verdict_label(run["recommendation"])
            lines.append(f"| {run['run']:>3} | {f} | {t} | {s} | {a} | **{total}** | {verdict} |")

        # Stats row
        for label, key in [("Mean", "mean"), ("Std Dev", "sd"), ("Min", "min"), ("Max", "max")]:
            vals = []
            for dim in DIMENSIONS:
                st = safe_stats([r[dim] for r in runs])
                if st[key] is not None:
                    vals.append(f"{st[key]:.1f}" if isinstance(st[key], float) else str(st[key]))
                else:
                    vals.append("—")
            total_st = safe_stats([r["total"] for r in runs])
            tv = (
                f"{total_st[key]:.1f}"
                if total_st[key] is not None and isinstance(total_st[key], float)
                else str(total_st[key] or "—")
            )
            lines.append(f"| **{label}** | {vals[0]} | {vals[1]} | {vals[2]} | {vals[3]} | **{tv}** | |")

        lines.append("")

    # --- Dimension Variance Summary ---
    lines.append("## Dimension Variance Summary")
    lines.append("")
    lines.append("Aggregated across all strategies:")
    lines.append("")
    lines.append("| Dimension | Mean | Std Dev | Min | Max | Range |")
    lines.append("|-----------|------|---------|-----|-----|-------|")

    for dim in DIMENSIONS:
        all_dim_scores = []
        for data in strategies.values():
            for run in data["runs"]:
                if run[dim] is not None:
                    all_dim_scores.append(run[dim])
        st = safe_stats(all_dim_scores)
        rng = (st["max"] - st["min"]) if st["max"] is not None and st["min"] is not None else "—"
        lines.append(
            f"| {dim.capitalize()} | {st['mean']:.2f} | {st['sd']:.2f} | "
            f"{st['min']} | {st['max']} | {rng} |"
        )

    total_st = safe_stats(all_totals)
    total_rng = (total_st["max"] - total_st["min"]) if total_st["max"] is not None else "—"
    lines.append(
        f"| **Total** | **{total_st['mean']:.2f}** | **{total_st['sd']:.2f}** | "
        f"**{total_st['min']}** | **{total_st['max']}** | **{total_rng}** |"
    )
    lines.append("")

    # --- Verdict Consistency Matrix ---
    lines.append("## Verdict Consistency")
    lines.append("")
    lines.append("| Strategy | Title | APPROVE | REVISE | REJECT | Consistency |")
    lines.append("|----------|-------|---------|--------|--------|-------------|")

    for rfe in sorted(strategies.keys()):
        data = strategies[rfe]
        title = (data["title"] or "")[:40]
        verdicts = [verdict_label(r["recommendation"]) for r in data["runs"]]
        n = len(verdicts)
        approve = sum(1 for v in verdicts if v == "APPROVE")
        revise = sum(1 for v in verdicts if v == "REVISE")
        reject = sum(1 for v in verdicts if v == "REJECT")
        if n > 0:
            most_common = max(set(verdicts), key=verdicts.count)
            consistency = verdicts.count(most_common) / n * 100
        else:
            consistency = 0
        lines.append(
            f"| {rfe} | {title} | {approve}/{n} | {revise}/{n} | "
            f"{reject}/{n} | **{consistency:.0f}%** |"
        )
    lines.append("")

    # --- Cross-Run Heatmap ---
    lines.append("## Cross-Run Total Scores")
    lines.append("")
    sorted_rfes = sorted(strategies.keys())
    header = "| Run | " + " | ".join(rfe.replace("RHAIRFE-", "") for rfe in sorted_rfes) + " |"
    sep = "|-----|" + "|".join("---" for _ in sorted_rfes) + "|"
    lines.append(header)
    lines.append(sep)

    max_runs = max(len(strategies[rfe]["runs"]) for rfe in sorted_rfes) if sorted_rfes else 0
    for run_idx in range(max_runs):
        row = f"| {run_idx + 1:>3} |"
        for rfe in sorted_rfes:
            runs = sorted(strategies[rfe]["runs"], key=lambda r: r["run"])
            if run_idx < len(runs):
                total = runs[run_idx].get("total", "—")
                row += f" {total} |"
            else:
                row += " — |"
        lines.append(row)
    lines.append("")

    # --- Prose Reviewer Variance ---
    lines.append("## Prose Reviewer Verdict Variance")
    lines.append("")
    lines.append("How often each prose reviewer gives approve vs revise/reject:")
    lines.append("")
    lines.append("| Strategy | Dimension | approve | revise | reject | other |")
    lines.append("|----------|-----------|---------|--------|--------|-------|")

    for rfe in sorted(strategies.keys()):
        data = strategies[rfe]
        for dim in DIMENSIONS:
            counts = defaultdict(int)
            for run in data["runs"]:
                v = run.get("reviewers", {}).get(dim, "")
                counts[verdict_label(v)] += 1
            n = len(data["runs"])
            lines.append(
                f"| {rfe} | {dim} | {counts.get('APPROVE', 0)}/{n} | "
                f"{counts.get('REVISE', 0)}/{n} | {counts.get('REJECT', 0)}/{n} | "
                f"{counts.get('UNKNOWN', 0)}/{n} |"
            )
    lines.append("")

    # --- Run Metadata ---
    lines.append("## Run Metadata")
    lines.append("")
    lines.append("| Run | Status | Create | Refine | Review | Total | Tasks | Reviews |")
    lines.append("|-----|--------|--------|--------|--------|-------|-------|---------|")

    for meta in sorted(run_metas, key=lambda m: m["run"]):
        run = meta["run"]
        status = meta.get("status", "?")
        cd = meta.get("create_duration", "?")
        rd = meta.get("refine_duration", "?")
        rvd = meta.get("review_duration", "?")
        td = meta.get("total_duration", "?")
        tasks = meta.get("tasks", "?")
        reviews = meta.get("reviews", "?")

        cd_str = f"{cd}s" if isinstance(cd, int) else cd
        rd_str = f"{rd}s" if isinstance(rd, int) else rd
        rvd_str = f"{rvd}s" if isinstance(rvd, int) else rvd
        td_str = f"{td // 60}m{td % 60}s" if isinstance(td, int) else td

        lines.append(
            f"| {run} | {status} | {cd_str} | {rd_str} | {rvd_str} | {td_str} | {tasks} | {reviews} |"
        )
    lines.append("")

    # --- Conclusions ---
    lines.append("## Conclusions")
    lines.append("")
    lines.append("*To be filled after reviewing the data above.*")
    lines.append("")

    return "\n".join(lines)


def main():
    results_dir = RESULTS_DIR
    if len(sys.argv) > 1:
        results_dir = Path(sys.argv[1])

    if not results_dir.exists():
        print(f"Error: results directory not found: {results_dir}", file=sys.stderr)
        sys.exit(1)

    strategies, run_metas = load_runs(results_dir)

    if not strategies:
        print("Error: no strategy data found in any run", file=sys.stderr)
        sys.exit(1)

    report = generate_report(strategies, run_metas)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(report, encoding="utf-8")
    print(f"Report written to {REPORT_PATH}")
    print(f"  {len(strategies)} strategies across {len(run_metas)} runs")


if __name__ == "__main__":
    main()
