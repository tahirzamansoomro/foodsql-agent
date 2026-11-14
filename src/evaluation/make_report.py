"""
FoodSQL-Agent  |  Build the tables, error analysis and charts for the paper

Reads every results/*.json file written by run_eval.py and produces:
    results/summary_table.md   results table (accuracy with 95% confidence interval)
    results/summary_table.csv  the same table as CSV
    results/error_analysis.md  why each configuration fails, with examples
    results/accuracy_chart.png accuracy bars (needs matplotlib)
    results/loss_curve.png     training loss (needs matplotlib and a results/train_log*.json file)

Run from the repository root:
    python src/evaluation/make_report.py
"""

import json
import math
from collections import Counter
from pathlib import Path

RESULTS = Path("results")
MIN_QUESTIONS = 50   # ignores smoke tests (--limit 5 / 10) and the oracle sanity check


def wilson(correct, n, z=1.96):
    """95% confidence interval for a proportion (in percent). Honest for small test sets."""
    if n == 0:
        return 0.0, 0.0
    p = correct / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return 100 * (centre - half), 100 * (centre + half)


def load_runs():
    runs = []
    for path in sorted(RESULTS.glob("*.json")):
        if path.name.startswith(("oracle", "smoke", "train_log")):
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        if "records" not in data or len(data["records"]) < MIN_QUESTIONS:
            continue
        tag = data["tag"]
        loop = "loop" if "_loop" in tag else "no loop"
        model = tag.replace("_noloop", "").replace("_loop", "")
        runs.append({"tag": tag, "model": model, "loop": loop, "records": data["records"]})
    return runs


def accuracy_cell(rows):
    n = len(rows)
    ok = sum(r["correct"] for r in rows)
    if n == 0:
        return "-"
    lo, hi = wilson(ok, n)
    return f"{100 * ok / n:.1f}% ({ok}/{n}; CI {lo:.0f}-{hi:.0f})"


def build_table(runs):
    header = ["Model", "Loop", "Execution accuracy", "In-distribution", "Held-out templates",
              "Valid SQL %", "Latency (s)", "Attempts", "Cost ($, list price)"]
    lines = [header]
    for run in sorted(runs, key=lambda r: (r["model"], r["loop"])):
        recs = run["records"]
        n = len(recs)
        lines.append([
            run["model"], run["loop"], accuracy_cell(recs),
            accuracy_cell([r for r in recs if r["split"] == "in_dist"]),
            accuracy_cell([r for r in recs if r["split"] == "held_out"]),
            f"{100 * sum(r['executes'] for r in recs) / n:.1f}",
            f"{sum(r['latency_s'] for r in recs) / n:.2f}",
            f"{sum(r['attempts'] for r in recs) / n:.2f}",
            f"{sum(r['cost_usd'] for r in recs):.3f}",
        ])
    return lines


def error_analysis(runs):
    out = ["# Error analysis\n"]
    for run in sorted(runs, key=lambda r: (r["model"], r["loop"])):
        recs = run["records"]
        failed = [r for r in recs if not r["correct"]]
        not_run = [r for r in failed if not r["executes"]]
        wrong = [r for r in failed if r["executes"]]
        out.append(f"\n## {run['tag']}\n")
        out.append(f"- failed {len(failed)} of {len(recs)}: {len(not_run)} did not run, "
                   f"{len(wrong)} ran but returned a wrong result\n")
        by_template = Counter(r["template_id"] for r in failed).most_common(6)
        out.append("- templates with most failures: " + ", ".join(f"{t} ({c})" for t, c in by_template) + "\n")
        errors = Counter((r["error"] or "")[:70] for r in not_run).most_common(3)
        if errors:
            out.append("- most common error messages: " + " | ".join(f"{e} ({c})" for e, c in errors) + "\n")
        for r in failed[:4]:
            out.append(f"\n**{r['id']}** ({r['split']}, {r['difficulty']}): {r['question']}\n")
            out.append(f"- gold: `{r['gold_sql']}`\n- model: `{r['pred_sql']}`\n")
    return "".join(out)


def make_charts(runs):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("matplotlib is not installed, skipping charts (pip install matplotlib)")
        return

    labels, overall, in_dist, held_out = [], [], [], []
    for run in sorted(runs, key=lambda r: (r["model"], r["loop"])):
        recs = run["records"]
        labels.append(f"{run['model']}\n{run['loop']}")
        for store, rows in ((overall, recs), (in_dist, [r for r in recs if r["split"] == "in_dist"]),
                            (held_out, [r for r in recs if r["split"] == "held_out"])):
            store.append(100 * sum(r["correct"] for r in rows) / max(1, len(rows)))
    x = range(len(labels))
    width = 0.27
    fig, ax = plt.subplots(figsize=(max(7, 1.8 * len(labels)), 4.5))
    ax.bar([i - width for i in x], overall, width, label="all questions")
    ax.bar(list(x), in_dist, width, label="in-distribution")
    ax.bar([i + width for i in x], held_out, width, label="held-out templates")
    ax.set_xticks(list(x))
    ax.set_xticklabels(labels, fontsize=7)
    ax.set_ylabel("Execution accuracy (%)")
    ax.set_ylim(0, 105)
    ax.legend()
    fig.tight_layout()
    fig.savefig(RESULTS / "accuracy_chart.png", dpi=200)
    print("saved results/accuracy_chart.png")

    logs = sorted(RESULTS.glob("train_log*.json"))
    if logs:
        fig, ax = plt.subplots(figsize=(6, 3.8))
        for path in logs:
            log = json.loads(path.read_text(encoding="utf-8"))
            ax.plot([e["update"] for e in log], [e["loss"] for e in log], label=path.stem.replace("train_log_", ""))
        ax.set_xlabel("optimizer update")
        ax.set_ylabel("training loss")
        ax.set_yscale("log")
        ax.legend()
        fig.tight_layout()
        fig.savefig(RESULTS / "loss_curve.png", dpi=200)
        print("saved results/loss_curve.png")


def main():
    runs = load_runs()
    if not runs:
        raise SystemExit("No full result files found in results/ (need runs with at least 50 questions).")

    table = build_table(runs)
    md = ["| " + " | ".join(table[0]) + " |", "|" + "---|" * len(table[0])]
    md += ["| " + " | ".join(row) + " |" for row in table[1:]]
    text = "\n".join(md)
    (RESULTS / "summary_table.md").write_text(text + "\n", encoding="utf-8")
    import csv
    with open(RESULTS / "summary_table.csv", "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows(table)
    (RESULTS / "error_analysis.md").write_text(error_analysis(runs), encoding="utf-8")

    print(text)
    print("\nsaved results/summary_table.md, summary_table.csv, error_analysis.md")
    make_charts(runs)


if __name__ == "__main__":
    main()
