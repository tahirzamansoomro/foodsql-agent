"""
FoodSQL-Agent  |  Schema description used in every prompt

The model must know the table and column names, otherwise it invents them
(hallucination). This module builds one fixed text description of the database
(tables, column types, keys, allowed category values) and saves it to
datasets/text2sql/schema.txt.

IMPORTANT: the SAME file is used for fine-tuning (on Kaggle, where the database
does not exist) and for evaluation. Training and testing prompts must be identical.

Create the file (run from the repository root, once):
    python src/agent/schema.py
"""

from pathlib import Path

DEFAULT_SCHEMA_PATH = Path("datasets") / "text2sql" / "schema.txt"

TABLES = ["restaurants", "riders", "customers", "orders", "deliveries"]

PRIMARY_KEYS = {
    "restaurants": "restaurant_id", "riders": "rider_id", "customers": "customer_id",
    "orders": "order_id", "deliveries": "order_id",
}

FOREIGN_KEYS = {
    "riders": ["riders.restaurant_id -> restaurants.restaurant_id"],
    "orders": [
        "orders.restaurant_id -> restaurants.restaurant_id",
        "orders.rider_id -> riders.rider_id",
        "orders.customer_id -> customers.customer_id",
    ],
    "deliveries": ["deliveries.order_id -> orders.order_id"],
}

COMMENTS = {
    "restaurants.city_code": "short city code, for example JAP or MUM",
    "riders.total_deliveries": "number of deliveries made by the rider",
    "riders.avg_rating": "average rating of the rider",
    "riders.avg_delivery_minutes": "average delivery time of the rider in minutes",
    "orders.city_type": "area type of the order",
    "orders.festival": "Yes if the order was placed on a festival day",
    "orders.order_amount": "value of the order",
    "deliveries.pickup_wait_min": "minutes between ordering and pickup",
    "deliveries.time_taken_min": "delivery duration in minutes",
    "deliveries.distance_km": "straight-line distance from restaurant to customer in km",
    "deliveries.rider_rating": "rating of the rider at the time of delivery",
    "deliveries.rider_age": "age of the rider at the time of delivery",
}

# Columns whose allowed values are listed in the prompt
VALUE_COLUMNS = {
    "restaurants": ["city_code"],
    "customers": ["membership"],
    "orders": ["order_type", "city_type", "festival", "payment_method"],
    "deliveries": ["weather", "road_traffic", "vehicle_type"],
}


def build_schema_text(con) -> str:
    """Read the real database and return the schema description as text."""
    lines = ["DuckDB database schema:"]
    for table in TABLES:
        lines.append("")
        lines.append(f"Table {table} (primary key: {PRIMARY_KEYS[table]})")
        for row in con.execute(f"DESCRIBE {table}").fetchall():
            name, col_type = row[0], row[1]
            comment = COMMENTS.get(f"{table}.{name}")
            lines.append(f"  {name} {col_type}" + (f"  -- {comment}" if comment else ""))
        for fk in FOREIGN_KEYS.get(table, []):
            lines.append(f"  Foreign key: {fk}")
        for col in VALUE_COLUMNS.get(table, []):
            values = [r[0] for r in con.execute(
                f"SELECT DISTINCT {col} FROM {table} WHERE {col} IS NOT NULL ORDER BY 1").fetchall()]
            lines.append(f"  Values of {col}: " + ", ".join(f"'{v}'" for v in values))
    return "\n".join(lines)


def save_schema(con, path=DEFAULT_SCHEMA_PATH) -> str:
    text = build_schema_text(con)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return text


def load_schema(path=DEFAULT_SCHEMA_PATH) -> str:
    return Path(path).read_text(encoding="utf-8")


def main():
    import duckdb

    db_file = Path.cwd() / "db" / "food_delivery.duckdb"
    con = duckdb.connect(str(db_file).replace("\\", "/"), read_only=True)
    text = save_schema(con)
    con.close()
    print(text)
    print(f"\n[Done] saved to {DEFAULT_SCHEMA_PATH} ({len(text)} characters)")


if __name__ == "__main__":
    main()
