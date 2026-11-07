"""
FoodSQL-Agent  |  Prompt templates

One fixed prompt format is used for GPT-4o, base Qwen, fine-tuned Qwen, and for the
fine-tuning data. If training and testing prompts differ, accuracy drops for no good reason.
"""

import re

SYSTEM_PROMPT = (
    "You are an expert DuckDB SQL assistant for a food-delivery database. "
    "Write one SQL query that answers the user's question.\n"
    "Rules:\n"
    "- Use only the tables and columns listed in the schema.\n"
    "- Return only the SQL query, with no explanation and no markdown.\n"
    "- When ranking or limiting rows, break ties by the id column in ascending order.\n\n"
)


def build_messages(schema: str, question: str) -> list:
    """First attempt: schema + question."""
    return [
        {"role": "system", "content": SYSTEM_PROMPT + schema},
        {"role": "user", "content": question},
    ]


def build_repair_messages(schema: str, question: str, bad_sql: str, error: str) -> list:
    """Repair attempt: show the model its failed query and the error message."""
    return build_messages(schema, question) + [
        {"role": "assistant", "content": bad_sql},
        {"role": "user", "content": (
            f"That query failed with this error:\n{error}\n"
            "Fix the query. Return only the corrected SQL query.")},
    ]


def extract_sql(text: str) -> str:
    """Pull the SQL out of a model answer (removes ``` fences and extra statements)."""
    text = (text or "").strip()
    fenced = re.search(r"```(?:sql)?\s*(.*?)```", text, re.S | re.I)
    if fenced:
        text = fenced.group(1).strip()
    if ";" in text:
        text = text.split(";")[0].strip()
    return text
