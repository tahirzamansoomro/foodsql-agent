"""
FoodSQL-Agent  |  Evaluation metrics

Execution accuracy: a predicted query is correct when running it gives the same
result table as the gold query. The SQL text may differ, only the result counts.

Comparison rules:
    - column names are ignored; numbers are rounded to 2 decimals (5 and 5.0 are equal)
    - if the gold query has ORDER BY, the row order must match; otherwise it does not matter
    - extra or missing columns count as wrong
"""

from datetime import date, datetime, time
from decimal import Decimal


def normalize_value(v):
    if v is None:
        return None
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float, Decimal)):
        return round(float(v), 2)
    if isinstance(v, (date, datetime, time)):
        return str(v)
    return str(v)


def normalize_rows(rows):
    return [tuple(normalize_value(v) for v in row) for row in rows]


def execute_rows(con, sql: str):
    """Run a query. Returns (rows, None) on success or (None, error_message) on failure."""
    try:
        return con.execute(sql).fetchall(), None
    except Exception as exc:
        return None, str(exc)[:300]


def results_match(gold_rows, pred_rows, ordered: bool) -> bool:
    gold, pred = normalize_rows(gold_rows), normalize_rows(pred_rows)
    if len(gold) != len(pred):
        return False
    if ordered:
        return gold == pred
    return sorted(gold, key=repr) == sorted(pred, key=repr)


def summarize(records: list) -> dict:
    """Aggregate per-question records into the numbers reported in the paper."""
    def block(rows):
        n = len(rows)
        if n == 0:
            return {"n": 0}
        return {
            "n": n,
            "execution_accuracy": round(100 * sum(r["correct"] for r in rows) / n, 1),
            "valid_sql_rate": round(100 * sum(r["executes"] for r in rows) / n, 1),
            "avg_latency_s": round(sum(r["latency_s"] for r in rows) / n, 2),
            "avg_attempts": round(sum(r["attempts"] for r in rows) / n, 2),
            "total_cost_usd": round(sum(r["cost_usd"] for r in rows), 4),
        }

    summary = {"overall": block(records), "by_split": {}, "by_difficulty": {}}
    for key, target in (("split", "by_split"), ("difficulty", "by_difficulty")):
        for value in sorted({r[key] for r in records}):
            summary[target][value] = block([r for r in records if r[key] == value])
    return summary
