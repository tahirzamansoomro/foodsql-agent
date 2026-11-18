
"""
FoodSQL-Agent | Hardened AST-based SQL validator

Security policy:
    - Exactly one read-only SELECT query is allowed.
    - Read-only CTEs and subqueries are supported.
    - Data modification and administrative statements are rejected.
    - External file access and potentially dangerous functions are blocked.
    - DuckDB EXPLAIN checks query validity before execution.

Note:
    This is a defensive application-level validation layer.
    It is not a substitute for database permissions or OS isolation.
"""

import sqlglot
from sqlglot import exp


# Explicitly forbidden SQL statement types.
FORBIDDEN_STATEMENTS = tuple(
    cls
    for cls in (
        getattr(exp, "Insert", None),
        getattr(exp, "Update", None),
        getattr(exp, "Delete", None),
        getattr(exp, "Create", None),
        getattr(exp, "Drop", None),
        getattr(exp, "Alter", None),
        getattr(exp, "Command", None),
        getattr(exp, "Transaction", None),
        getattr(exp, "Merge", None),
        getattr(exp, "Copy", None),
        getattr(exp, "Pragma", None),
        getattr(exp, "Attach", None),
        getattr(exp, "Detach", None),
        getattr(exp, "Grant", None),
        getattr(exp, "Revoke", None),
        getattr(exp, "Use", None),
    )
    if cls is not None
)


# Functions that can access external resources or load executable code.
FORBIDDEN_FUNCTIONS = {
    "read_csv",
    "read_csv_auto",
    "read_parquet",
    "read_json",
    "read_json_auto",
    "read_text",
    "read_blob",
    "read_ndjson",
    "parquet_scan",
    "csv_scan",
    "json_scan",
    "glob",
    "query",
    "query_table",
    "query_table_function",
    "sqlite_scan",
    "postgres_scan",
    "mysql_scan",
    "iceberg_scan",
    "delta_scan",
    "httpfs",
    "http_get",
    "http_post",
    "ftp_get",
    "install_extension",
    "load_extension",
    "set_variable",
    "getenv",
    "current_setting",
}


def _function_name(node):
    """Extract a normalized SQL function name."""
    name = getattr(node, "name", None)

    if callable(name):
        try:
            name = name()
        except Exception:
            name = None

    if name:
        return str(name).lower()

    sql_name = getattr(node, "sql_name", None)
    if callable(sql_name):
        try:
            return str(sql_name()).lower()
        except Exception:
            pass

    return ""


def check_read_only(sql: str):
    """Reject SQL outside the application's read-only query policy."""

    if not sql or not sql.strip():
        return "The query is empty."

    try:
        statements = sqlglot.parse(sql, read="duckdb")
    except sqlglot.errors.ParseError as exc:
        return f"SQL parsing failed: {str(exc)[:300]}"

    if len(statements) != 1 or statements[0] is None:
        return "Only one SQL statement is allowed."

    tree = statements[0]

    # Allow SELECT and query expressions such as WITH ... SELECT.
    if not isinstance(tree, exp.Query):
        return "Only read-only SELECT queries are allowed."

    # Inspect the complete AST, including nested queries and CTEs.
    for node in tree.walk():

        if isinstance(node, FORBIDDEN_STATEMENTS):
            return (
                f"Operation '{type(node).__name__}' "
                "is not allowed."
            )

        # Reject external-resource and dangerous functions.
        if isinstance(node, exp.Func):
            function_name = _function_name(node)

            if function_name in FORBIDDEN_FUNCTIONS:
                return (
                    f"Function '{function_name}' "
                    "is not allowed."
                )

        # DuckDB table functions may be represented as Anonymous.
        if isinstance(node, exp.Anonymous):
            function_name = _function_name(node)

            if function_name in FORBIDDEN_FUNCTIONS:
                return (
                    f"Function '{function_name}' "
                    "is not allowed."
                )

    return None


def validate(con, sql: str):
    """Return (ok, error_message) after AST and EXPLAIN checks."""

    problem = check_read_only(sql)

    if problem:
        return False, problem

    try:
        clean_sql = sql.strip().rstrip(";")
        con.execute("EXPLAIN " + clean_sql).fetchall()

    except Exception as exc:
        return False, str(exc)[:400]

    return True, None
