"""
FoodSQL-Agent  |  SQL validator

Two checks before a generated query is accepted:
    1. Safety   : only a single read-only SELECT / WITH statement is allowed.
    2. EXPLAIN  : DuckDB parses and plans the query WITHOUT running it. This catches
                  syntax errors and wrong table or column names, and the error text
                  is sent back to the model so that it can repair the query.
"""

import re

FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|attach|detach|copy|pragma|install|load|"
    r"export|import|call|set)\b", re.I)


def check_read_only(sql: str):
    """Return an error message if the query is not a single read-only statement, else None."""
    cleaned = (sql or "").strip().rstrip(";").strip()
    if not cleaned:
        return "The query is empty."
    if ";" in cleaned:
        return "Only one SQL statement is allowed."
    if not re.match(r"(select|with)\b", cleaned, re.I):
        return "Only SELECT queries are allowed."
    bad = FORBIDDEN.search(cleaned)
    if bad:
        return f"The keyword '{bad.group(1).upper()}' is not allowed (read-only queries only)."
    return None


def validate(con, sql: str):
    """Return (ok, error_message). error_message is None when the query is valid."""
    problem = check_read_only(sql)
    if problem:
        return False, problem
    try:
        con.execute("EXPLAIN " + sql.strip().rstrip(";")).fetchall()
    except Exception as exc:
        return False, str(exc)[:400]
    return True, None
