import json
import csv
from pathlib import Path

RESULTS = Path("results")

experiments = [
    ("Main Benchmark — Prompt V5", "gemini_full_prompt_v5.json"),
    ("Independent Robustness — Prompt V8", "gemini_prompt_v8_robustness20.json"),
]

rows = []

for name, filename in experiments:
    data = json.loads((RESULTS / filename).read_text(encoding="utf-8"))
    records = data["records"]
    n = len(records)

    correct = sum(bool(r["correct"]) for r in records)
    valid = sum(bool(r["executes"]) for r in records)

    row = {
        "Experiment": name,
        "Questions": n,
        "Correct": correct,
        "Execution Accuracy (%)": round(correct / n * 100, 2),
        "Valid SQL Rate (%)": round(valid / n * 100, 2),
        "Average Latency (s)": round(sum(r["latency_s"] for r in records) / n, 2),
        "Average Attempts": round(sum(r["attempts"] for r in records) / n, 2),
        "Total API Cost ($)": round(sum(r["cost_usd"] for r in records), 4),
    }
    rows.append(row)

# Markdown summary
md = [
    "# FoodSQL-Agent — Final Evaluation Summary",
    "",
    "The two Text-to-SQL experiments use separate datasets and prompt versions.",
    "Their accuracy results must be interpreted independently.",
    "",
    "| " + " | ".join(rows[0].keys()) + " |",
    "|" + "|".join(["---"] * len(rows[0])) + "|",
]

for row in rows:
    md.append("| " + " | ".join(str(v) for v in row.values()) + " |")

md += [
    "",
    "## Difficulty-wise Results",
    "",
]

for name, filename in experiments:
    records = json.loads((RESULTS / filename).read_text(encoding="utf-8"))["records"]
    md.append(f"### {name}")
    md.append("")
    md.append("| Difficulty | Questions | Correct | Accuracy |")
    md.append("|---|---:|---:|---:|")

    for difficulty in ("easy", "medium", "hard"):
        subset = [r for r in records if r["difficulty"].lower() == difficulty]
        if subset:
            count = len(subset)
            hits = sum(bool(r["correct"]) for r in subset)
            md.append(f"| {difficulty.title()} | {count} | {hits} | {hits/count*100:.1f}% |")
    md.append("")

(RESULTS / "summary_table.md").write_text("\n".join(md) + "\n", encoding="utf-8")

# CSV summary
with open(RESULTS / "summary_table.csv", "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
    writer.writeheader()
    writer.writerows(rows)

# Accuracy chart
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

labels = ["Prompt V5\nMain Benchmark", "Prompt V8\nRobustness"]
accuracy = [r["Execution Accuracy (%)"] for r in rows]
valid_sql = [r["Valid SQL Rate (%)"] for r in rows]

x = range(len(labels))
width = 0.34

fig, ax = plt.subplots(figsize=(8, 5))
ax.bar([i - width/2 for i in x], accuracy, width, label="Execution accuracy")
ax.bar([i + width/2 for i in x], valid_sql, width, label="Valid SQL rate")

ax.set_ylabel("Rate (%)")
ax.set_title("FoodSQL-Agent — Text-to-SQL Evaluation")
ax.set_xticks(list(x))
ax.set_xticklabels(labels)
ax.set_ylim(0, 110)
ax.legend()

for i, value in enumerate(accuracy):
    ax.text(i - width/2, value + 1, f"{value:.1f}%", ha="center")

for i, value in enumerate(valid_sql):
    ax.text(i + width/2, value + 1, f"{value:.1f}%", ha="center")

fig.tight_layout()
fig.savefig(RESULTS / "accuracy_chart.png", dpi=200)
plt.close(fig)

print("\n".join(md))
print("\nUpdated:")
print("results/summary_table.md")
print("results/summary_table.csv")
print("results/accuracy_chart.png")
