"""
FoodSQL-Agent  |  Step 2A: Generate customers, order amounts and payment methods

The Kaggle dataset has no customers, no order amounts and no payment information.
This script adds them with plain Python (no LLM, no API cost). Everything here is
SYNTHETIC and is generated with a fixed random seed, so every run gives the same data.

What it does:
    1. Creates a new table:  customers(customer_id, city_code, signup_date, membership)
    2. Adds three columns to the orders table: customer_id, order_amount, payment_method

Run from the repository root, AFTER build_pipeline.py:
    python src/data_generation/generate_basic_tables.py

Note: build_pipeline.py recreates the orders table, so if you run it again,
run this script again afterwards.
"""

from pathlib import Path

import numpy as np
import pandas as pd

# ----------------------------------------------------------------------------
# Settings (change these here, not inside the code)
# ----------------------------------------------------------------------------
SEED = 42                      # fixed seed: same data on every run
ORDERS_PER_CUSTOMER = 6        # on average, one customer places about 6 orders
MIN_CUSTOMERS_PER_CITY = 5     # every city gets at least this many customers
MAX_DAYS_BEFORE_FIRST_ORDER = 540   # customers sign up up to ~18 months before the data starts

# Typical order value by order type (synthetic, in local currency units)
BASE_AMOUNT = {"Snack": 400, "Drinks": 300, "Meal": 900, "Buffet": 1500}
DEFAULT_AMOUNT = 500           # used when order_type is missing
FESTIVAL_UPLIFT = 1.10         # orders during a festival are about 10% larger

# Payment methods and how likely each one is
PAYMENT_METHODS = ["Cash", "Card", "Wallet"]
PAYMENT_PROBS = [0.45, 0.30, 0.25]

# Membership types and how likely each one is
MEMBERSHIPS = ["Free", "Plus"]
MEMBERSHIP_PROBS = [0.80, 0.20]


def generate(orders: pd.DataFrame, first_order_date, seed: int = SEED):
    """
    Build the customers table and the extra order columns.

    orders           : DataFrame with columns order_id, order_type, festival, city_code
    first_order_date : date of the earliest order (customers must sign up before it)
    Returns          : (customers_df, order_extras_df)
    """
    rng = np.random.default_rng(seed)
    orders = orders.copy()

    # Fill missing values so the code below never fails
    orders["city_code"] = orders["city_code"].fillna("UNKNOWN")
    orders["festival"] = orders["festival"].fillna("No")

    # ------------------------------------------------------------------
    # 1. Customers: created per city, and each order is assigned to a
    #    customer from the SAME city (people order from their own city).
    # ------------------------------------------------------------------
    customer_ids = np.empty(len(orders), dtype=object)
    customer_rows = []
    counter = 0

    for city, positions in orders.groupby("city_code").indices.items():
        n_orders = len(positions)
        n_customers = max(MIN_CUSTOMERS_PER_CITY, n_orders // ORDERS_PER_CUSTOMER)
        ids = np.array([f"C{counter + i:05d}" for i in range(1, n_customers + 1)])
        counter += n_customers

        # Some customers order much more often than others (uneven weights)
        weights = rng.gamma(shape=1.5, scale=1.0, size=n_customers)
        probs = weights / weights.sum()
        chosen = rng.choice(n_customers, size=n_orders, p=probs)
        customer_ids[positions] = ids[chosen]

        for cid in ids:
            customer_rows.append((cid, city))

    orders["customer_id"] = customer_ids

    customers = pd.DataFrame(customer_rows, columns=["customer_id", "city_code"])
    # Keep only customers who actually placed an order (clean foreign keys)
    customers = customers[customers["customer_id"].isin(set(customer_ids))].reset_index(drop=True)

    # Signup date: some time before the first order in the dataset
    days_before = rng.integers(1, MAX_DAYS_BEFORE_FIRST_ORDER + 1, size=len(customers))
    signup = pd.Series(pd.Timestamp(first_order_date) - pd.to_timedelta(days_before, unit="D"))
    customers["signup_date"] = signup.dt.date
    customers["membership"] = rng.choice(MEMBERSHIPS, size=len(customers), p=MEMBERSHIP_PROBS)

    # ------------------------------------------------------------------
    # 2. Order amount: base value by order type, festival uplift, random noise
    # ------------------------------------------------------------------
    base = orders["order_type"].map(BASE_AMOUNT).fillna(DEFAULT_AMOUNT).to_numpy(dtype=float)
    uplift = np.where(orders["festival"].eq("Yes"), FESTIVAL_UPLIFT, 1.0)
    noise = rng.lognormal(mean=0.0, sigma=0.25, size=len(orders))   # +/- 25% variation
    amount = np.round(base * uplift * noise / 10) * 10               # round to nearest 10
    orders["order_amount"] = amount.astype(int)

    # ------------------------------------------------------------------
    # 3. Payment method
    # ------------------------------------------------------------------
    orders["payment_method"] = rng.choice(PAYMENT_METHODS, size=len(orders), p=PAYMENT_PROBS)

    extras = orders[["order_id", "customer_id", "order_amount", "payment_method"]]
    return customers, extras


def main():
    import duckdb  # imported here so generate() can be tested without DuckDB

    db_file = Path.cwd() / "db" / "food_delivery.duckdb"
    if not db_file.exists():
        raise FileNotFoundError(f"{db_file} not found. Run build_pipeline.py first.")

    con = duckdb.connect(str(db_file).replace("\\", "/"))

    # Read what we need from the Gold tables (ORDER BY keeps the result reproducible)
    orders = con.execute("""
        SELECT o.order_id, o.order_type, o.festival, r.city_code
        FROM orders o
        JOIN restaurants r USING (restaurant_id)
        ORDER BY o.order_id
    """).fetchdf()
    first_order_date = con.execute("SELECT MIN(order_date) FROM orders").fetchall()[0][0]

    customers_df, extras_df = generate(orders, first_order_date)

    # --- Write the customers table ---
    con.register("customers_df", customers_df)
    con.execute("""
        CREATE OR REPLACE TABLE customers AS
        SELECT customer_id,
               city_code,
               CAST(signup_date AS DATE) AS signup_date,
               membership
        FROM customers_df
    """)

    # --- Rebuild the orders table with the three new columns ---
    # We build a new table first, then swap it in (safer than replacing a table
    # while reading from it). Listing the columns explicitly makes this script
    # safe to run more than once.
    con.register("extras_df", extras_df)
    con.execute("DROP TABLE IF EXISTS orders_new")
    con.execute("""
        CREATE TABLE orders_new AS
        SELECT o.order_id,
               o.restaurant_id,
               o.rider_id,
               x.customer_id,                 -- foreign key -> customers
               o.order_date,
               o.order_time,
               o.order_type,
               o.city_type,
               o.festival,
               o.multiple_deliveries,
               x.order_amount,
               x.payment_method
        FROM orders o
        JOIN extras_df x USING (order_id)
    """)
    con.execute("DROP TABLE orders")
    con.execute("ALTER TABLE orders_new RENAME TO orders")

    # ------------------------------------------------------------------
    # Checks
    # ------------------------------------------------------------------
    print("[Done] customers:", con.execute("SELECT COUNT(*) FROM customers").fetchall()[0][0])
    print("[Done] orders   :", con.execute("SELECT COUNT(*) FROM orders").fetchall()[0][0])

    print("\n[Check] orders table columns:")
    print(con.execute("DESCRIBE orders").fetchdf()[["column_name", "column_type"]])

    print("\n[Check] Orders per customer (min / avg / max):")
    print(con.execute("""
        SELECT MIN(n) AS min_orders, ROUND(AVG(n), 1) AS avg_orders, MAX(n) AS max_orders
        FROM (SELECT customer_id, COUNT(*) AS n FROM orders GROUP BY customer_id)
    """).fetchdf())

    print("\n[Check] Order amount by order type:")
    print(con.execute("""
        SELECT order_type, COUNT(*) AS n,
               MIN(order_amount) AS min_amount,
               ROUND(AVG(order_amount)) AS avg_amount,
               MAX(order_amount) AS max_amount
        FROM orders GROUP BY order_type ORDER BY avg_amount DESC
    """).fetchdf())

    print("\n[Check] Payment method share:")
    print(con.execute("""
        SELECT payment_method, COUNT(*) AS n,
               ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 1) AS pct
        FROM orders GROUP BY payment_method ORDER BY n DESC
    """).fetchdf())

    print("\n[Check] Orders whose customer is missing from customers (should be 0):")
    print(con.execute("""
        SELECT COUNT(*) AS orphan_orders
        FROM orders o LEFT JOIN customers c USING (customer_id)
        WHERE c.customer_id IS NULL
    """).fetchdf())

    print("\n[Test] Top 5 customers by total spend:")
    print(con.execute("""
        SELECT c.customer_id, c.city_code, c.membership,
               COUNT(*) AS total_orders, SUM(o.order_amount) AS total_spent
        FROM orders o JOIN customers c USING (customer_id)
        GROUP BY c.customer_id, c.city_code, c.membership
        ORDER BY total_spent DESC, c.customer_id LIMIT 5
    """).fetchdf())

    con.close()


if __name__ == "__main__":
    main()