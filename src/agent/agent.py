"""
FoodSQL-Agent  |  The self-correcting Text-to-SQL agent

Flow:
    question -> model writes SQL -> validator (EXPLAIN dry run)
        valid   -> done
        invalid -> the error is sent back to the model -> it writes a corrected query
                   (at most max_repairs repairs, so at most 1 + max_repairs attempts)

With use_loop=False the agent makes a single attempt (the "without loop" setting
of the 2x2 experiment).
"""

from src.agent.prompts import build_messages, build_repair_messages, extract_sql
from src.agent.validator import validate


class SQLAgent:
    def __init__(self, model, con, schema: str, use_loop: bool = True, max_repairs: int = 3):
        self.model = model
        self.con = con
        self.schema = schema
        self.use_loop = use_loop
        self.max_repairs = max_repairs

    def answer(self, question: str) -> dict:
        messages = build_messages(self.schema, question)
        trace = []
        totals = {"latency_s": 0.0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}
        sql, ok = "", False
        max_attempts = 1 + (self.max_repairs if self.use_loop else 0)

        for attempt in range(1, max_attempts + 1):
            result = self.model.generate(messages)
            for key in totals:
                totals[key] += result[key]
            sql = extract_sql(result["text"])
            ok, error = validate(self.con, sql)
            trace.append({"attempt": attempt, "sql": sql, "valid": ok, "error": error})
            if ok or attempt == max_attempts:
                break
            messages = build_repair_messages(self.schema, question, sql, error)

        return {"sql": sql, "valid": ok, "attempts": len(trace), "trace": trace, **totals}
