
"""
FoodSQL-Agent | Self-correcting Text-to-SQL agent

Flow:
    question
      -> generate SQL
      -> validate with EXPLAIN
      -> execute SQL
      -> return columns and rows

If validation or execution fails, the error is sent back to
the model for correction (up to max_repairs).
"""

from datetime import date, datetime
from decimal import Decimal
from time import perf_counter

from src.agent.prompts import build_messages, build_repair_messages, extract_sql
from src.agent.validator import validate


class SQLAgent:
    def __init__(
        self,
        model,
        con,
        schema: str,
        use_loop: bool = True,
        max_repairs: int = 3,
        max_rows: int = 100,
    ):
        self.model = model
        self.con = con
        self.schema = schema
        self.use_loop = use_loop
        self.max_repairs = max_repairs
        self.max_rows = max_rows

    @staticmethod
    def _serialize_value(value):
        """Convert common database values into JSON-friendly values."""
        if isinstance(value, (datetime, date)):
            return value.isoformat()
        if isinstance(value, Decimal):
            return float(value)
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")
        return value

    def _execute_query(self, sql: str) -> dict:
        """Execute validated SQL and return a bounded result preview."""
        cursor = self.con.execute(sql)

        columns = [item[0] for item in cursor.description or []]
        fetched = cursor.fetchmany(self.max_rows + 1)

        truncated = len(fetched) > self.max_rows
        fetched = fetched[:self.max_rows]

        rows = [
            {
                column: self._serialize_value(value)
                for column, value in zip(columns, row)
            }
            for row in fetched
        ]

        return {
            "columns": columns,
            "rows": rows,
            "row_count": len(rows),
            "truncated": truncated,
        }

    def answer(self, question: str) -> dict:
        # Measure the complete agent processing time.
        start_time = perf_counter()

        messages = build_messages(self.schema, question)

        trace = []
        totals = {
            "latency_s": 0.0,
            "input_tokens": 0,
            "output_tokens": 0,
            "cost_usd": 0.0,
        }

        sql = ""
        ok = False
        result_data = {
            "columns": [],
            "rows": [],
            "row_count": 0,
            "truncated": False,
        }

        max_attempts = 1 + (self.max_repairs if self.use_loop else 0)

        for attempt in range(1, max_attempts + 1):
            result = self.model.generate(messages)

            for key in totals:
                totals[key] += result[key]

            sql = extract_sql(result["text"])
            valid, error = validate(self.con, sql)

            execution_error = None
            executed = False

            if valid:
                try:
                    result_data = self._execute_query(sql)
                    executed = True
                except Exception as exc:
                    execution_error = str(exc)[:400]
                    error = execution_error

            trace.append({
                "attempt": attempt,
                "sql": sql,
                "valid": valid,
                "executed": executed,
                "error": error,
            })

            if executed:
                ok = True
                break

            if attempt == max_attempts:
                break

            messages = build_repair_messages(
                self.schema,
                question,
                sql,
                error or "The query could not be executed.",
            )

        # Total time includes model generation, validation,
        # SQL execution, and agent processing.
        total_latency_s = perf_counter() - start_time

        return {
            "sql": sql,
            "valid": ok,
            "success": ok,
            "attempts": len(trace),
            "trace": trace,
            **result_data,
            **totals,
            "total_latency_s": total_latency_s,
            "total_latency_ms": round(total_latency_s * 1000, 2),
        }
