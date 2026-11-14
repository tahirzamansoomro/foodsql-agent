"""
FoodSQL-Agent  |  Run a model on the test set

Examples (run from the repository root):

    # 1. Sanity check of the whole pipeline: the "oracle" returns the gold SQL,
    #    so execution accuracy MUST be 100%. No model download, no cost.
    python src/evaluation/run_eval.py --model oracle

    # 2. Quick test of a small local model on 10 questions
    python src/evaluation/run_eval.py --model hf --model-id Qwen/Qwen2.5-Coder-1.5B-Instruct --limit 10

    # 3. Full runs, with and without the self-correction loop
    python src/evaluation/run_eval.py --model hf --model-id Qwen/Qwen2.5-Coder-3B-Instruct
    python src/evaluation/run_eval.py --model hf --model-id Qwen/Qwen2.5-Coder-3B-Instruct --no-loop
    python src/evaluation/run_eval.py --model openai --model-id gpt-4o
    python src/evaluation/run_eval.py --model gemini --model-id gemini-3.5-flash-lite

    # 4. A fine-tuned model (QLoRA adapter folder)
    python src/evaluation/run_eval.py --model hf --model-id Qwen/Qwen2.5-Coder-7B-Instruct --adapter outputs/qwen7b-lora

Results are saved in results/<tag>.json (summary + every question).
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # makes "src" importable

from src.agent.agent import SQLAgent
from src.agent.models import ChatModel
from src.agent.schema import DEFAULT_SCHEMA_PATH, load_schema
from src.evaluation.metrics import execute_rows, results_match, summarize


class OracleModel(ChatModel):
    """Returns the gold SQL. Used only to prove that the evaluation code itself is correct."""
    name = "oracle"

    def __init__(self, items):
        self.answers = {it["question"]: it["sql"] for it in items}

    def generate(self, messages):
        # messages[1] is always the original user question
        return {"text": self.answers[messages[1]["content"]], "latency_s": 0.0,
                "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}


def load_jsonl(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def evaluate(con, items, agent, progress=None):
    """Run the agent on every test item and compare results with the gold SQL."""
    records = []
    iterator = progress(items) if progress else items
    for item in iterator:
        gold_rows, gold_error = execute_rows(con, item["sql"])
        if gold_error:  # should never happen; reported instead of hidden
            raise RuntimeError(f"Gold SQL failed for {item['id']}: {gold_error}")
        try:
            res = agent.answer(item["question"])
        except RuntimeError as exc:  # for example the daily API limit: keep what we have so far
            print(f"\n[Stopped early after {len(records)} questions] {exc}")
            break
        pred_rows, pred_error = execute_rows(con, res["sql"]) if res["sql"] else (None, "empty query")
        executes = pred_error is None
        correct = executes and results_match(gold_rows, pred_rows, "ORDER BY" in item["sql"].upper())
        records.append({
            "id": item["id"], "split": item["split"], "difficulty": item["difficulty"],
            "template_id": item["template_id"], "question": item["question"],
            "gold_sql": item["sql"], "pred_sql": res["sql"], "correct": bool(correct),
            "executes": bool(executes), "error": pred_error, "attempts": res["attempts"],
            "latency_s": res["latency_s"], "input_tokens": res["input_tokens"],
            "output_tokens": res["output_tokens"], "cost_usd": res["cost_usd"],
        })
    return records


def print_summary(tag, summary):
    o = summary["overall"]
    print(f"\n=== {tag} ===")
    print(f"questions {o['n']} | execution accuracy {o['execution_accuracy']}% | valid SQL {o['valid_sql_rate']}% | "
          f"latency {o['avg_latency_s']}s | attempts {o['avg_attempts']} | cost ${o['total_cost_usd']}")
    for group in ("by_split", "by_difficulty"):
        for name, b in summary[group].items():
            print(f"  {group[3:]:<11} {name:<9} n={b['n']:<3} accuracy {b['execution_accuracy']}%")


def main():
    import duckdb
    from tqdm import tqdm

    p = argparse.ArgumentParser()
    p.add_argument("--model", choices=["oracle", "openai", "gemini", "hf"], required=True)
    p.add_argument("--rpm", type=int, default=8, help="Gemini: maximum requests per minute")
    p.add_argument("--model-id", default=None)
    p.add_argument("--adapter", default=None, help="folder of a QLoRA adapter (fine-tuned model)")
    p.add_argument("--no-loop", action="store_true", help="single attempt, no self-correction")
    p.add_argument("--max-repairs", type=int, default=3)
    p.add_argument("--limit", type=int, default=None, help="use only the first N test questions")
    p.add_argument("--split", choices=["all", "in_dist", "held_out"], default="all")
    p.add_argument("--tag", default=None)
    p.add_argument("--db", default="db/food_delivery.duckdb")
    p.add_argument("--test", default="datasets/text2sql/test.jsonl")
    p.add_argument("--schema", default=str(DEFAULT_SCHEMA_PATH))
    args = p.parse_args()

    items = load_jsonl(args.test)
    if args.split != "all":
        items = [it for it in items if it["split"] == args.split]
    if args.limit:
        items = items[: args.limit]

    if args.model == "oracle":
        model = OracleModel(load_jsonl(args.test))
    elif args.model == "openai":
        from src.agent.models import OpenAIModel
        model = OpenAIModel(args.model_id or "gpt-4o")
    elif args.model == "gemini":
        from src.agent.models import GeminiModel
        model = GeminiModel(args.model_id or "gemini-3.5-flash-lite", rpm=args.rpm)
    else:
        from src.agent.models import HFModel
        if not args.model_id:
            p.error("--model-id is required for --model hf")
        model = HFModel(args.model_id, adapter_path=args.adapter)

    con = duckdb.connect(args.db.replace("\\", "/"), read_only=True)
    agent = SQLAgent(model, con, load_schema(args.schema), use_loop=not args.no_loop,
                     max_repairs=args.max_repairs)

    records = evaluate(con, items, agent, progress=lambda x: tqdm(x, desc=model.name))
    if not records:
        raise SystemExit("No question was answered, nothing to save.")
    summary = summarize(records)

    tag = args.tag or f"{model.name}_{'noloop' if args.no_loop else 'loop'}" + (
        f"_{args.split}" if args.split != "all" else "") + (f"_n{args.limit}" if args.limit else "") + (
        "_partial" if len(records) < len(items) else "")
    out = Path("results") / f"{tag}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps({"tag": tag, "summary": summary, "records": records}, indent=2), encoding="utf-8")

    print_summary(tag, summary)
    print(f"\nSaved: {out}")
    con.close()


if __name__ == "__main__":
    main()
