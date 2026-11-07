"""
FoodSQL-Agent  |  Step 3: Build the Text-to-SQL training set and benchmark (test set)

Every (question, SQL) pair is created from a SQL template, and every SQL query is
EXECUTED on the Gold database to prove that it runs and returns a real, non-empty
result. This means the gold SQL is correct by construction and no LLM or API cost
is needed. (Using GPT-4o to write the training data would also bias the later
GPT-4o vs. Qwen comparison, so we avoid it.)

Test set = two parts:
    in_dist  : SQL queries from the same template families as training, but with
               parameter values (and therefore SQL text) that never appear in training
    held_out : template families that never appear in training at all
               (window functions, NOT EXISTS, CTEs, date functions, ...)

Outputs (small files, committed to git):
    datasets/text2sql/train.jsonl
    datasets/text2sql/test.jsonl

Run from the repository root, after build_pipeline.py and generate_basic_tables.py:
    python src/benchmark/build_datasets.py
"""

import json
import random
from collections import Counter, defaultdict
from pathlib import Path

SEED = 42
MAX_ROWS = 60              # reject queries that return more rows than this
DRAWS_PER_TEMPLATE = 80    # parameter draws tried per template
MAX_TRAIN = 2000           # maximum number of training pairs
IN_DIST_PER_TEMPLATE = 6   # maximum in-distribution test queries per template
HELD_OUT_PER_TEMPLATE = 5  # maximum held-out test queries per template
IN_DIST_TOTAL = 100        # maximum in-distribution test queries in total

MONTH_NAMES = {1: "January", 2: "February", 3: "March", 4: "April", 5: "May", 6: "June",
               7: "July", 8: "August", 9: "September", 10: "October", 11: "November", 12: "December"}


def make(tid, difficulty, nl, sql, params=()):
    """One template: id, difficulty, question variants, SQL, and the parameters it needs."""
    return {"id": tid, "difficulty": difficulty, "nl": nl, "sql": " ".join(sql.split()), "params": params}


# ----------------------------------------------------------------------------
# TRAIN-FAMILY TEMPLATES
# ----------------------------------------------------------------------------
# Tie-breakers (for example ", restaurant_id") are always added to ORDER BY so the
# correct answer is never ambiguous when two groups have the same value.
TRAIN_TEMPLATES = [
    # ---------------- easy: one table ----------------
    make("E01", "easy", ["How many orders were paid by {payment}?", "Count the orders paid with {payment}.", "What is the number of {payment} orders?"],
         "SELECT COUNT(*) AS total_orders FROM orders WHERE payment_method = '{payment}'", ("payment",)),
    make("E02", "easy", ["What is the average order amount for {order_type} orders?", "Average amount of {order_type} orders?", "How much does a {order_type} order cost on average?"],
         "SELECT ROUND(AVG(order_amount), 2) AS avg_amount FROM orders WHERE order_type = '{order_type}'", ("order_type",)),
    make("E03", "easy", ["How many orders were placed during festivals?", "Count the festival orders.", "What is the number of orders placed on festival days?"],
         "SELECT COUNT(*) AS festival_orders FROM orders WHERE festival = 'Yes'"),
    make("E04", "easy", ["How many riders have an average rating above {rating}?", "Count the riders rated higher than {rating} on average.", "Number of riders whose average rating exceeds {rating}?"],
         "SELECT COUNT(*) AS n_riders FROM riders WHERE avg_rating > {rating}", ("rating",)),
    make("E05", "easy", ["How many customers have a {membership} membership?", "Count the customers with {membership} membership.", "What is the number of {membership} members?"],
         "SELECT COUNT(*) AS n_customers FROM customers WHERE membership = '{membership}'", ("membership",)),
    make("E06", "easy", ["What is the average delivery time when the weather is {weather}?", "Average delivery time in {weather} weather?", "How long do deliveries take on average in {weather} conditions?"],
         "SELECT ROUND(AVG(time_taken_min), 2) AS avg_minutes FROM deliveries WHERE weather = '{weather}'", ("weather",)),
    make("E07", "easy", ["How many deliveries took longer than {minutes} minutes?", "Count the deliveries slower than {minutes} minutes.", "Number of deliveries that took more than {minutes} minutes?"],
         "SELECT COUNT(*) AS slow_deliveries FROM deliveries WHERE time_taken_min > {minutes}", ("minutes",)),
    make("E08", "easy", ["What is the total order revenue in {month_name}?", "Total revenue for {month_name}?", "How much money did orders bring in during {month_name}?"],
         "SELECT SUM(order_amount) AS total_revenue FROM orders WHERE MONTH(order_date) = {month_num}", ("month",)),
    make("E09", "easy", ["How many orders were placed with each payment method?", "Number of orders per payment method.", "Count the orders for every payment method."],
         "SELECT payment_method, COUNT(*) AS n FROM orders GROUP BY payment_method ORDER BY n DESC, payment_method"),
    make("E10", "easy", ["What is the average delivery distance in {traffic} traffic?", "Average distance of deliveries made in {traffic} traffic?", "How far are deliveries on average when traffic is {traffic}?"],
         "SELECT ROUND(AVG(distance_km), 2) AS avg_km FROM deliveries WHERE road_traffic = '{traffic}'", ("traffic",)),
    make("E11", "easy", ["How many restaurants are there in {city}?", "Count the restaurants in {city}.", "Number of restaurants located in {city}?"],
         "SELECT COUNT(*) AS n_restaurants FROM restaurants WHERE city_code = '{city}'", ("city",)),
    make("E12", "easy", ["Which {n} riders have made the most deliveries?", "List the top {n} riders by total deliveries.", "Show the {n} riders with the highest number of deliveries."],
         "SELECT rider_id, total_deliveries FROM riders ORDER BY total_deliveries DESC, rider_id LIMIT {n}", ("n",)),
    make("E13", "easy", ["How many orders were placed in {city_type} areas?", "Count the orders from {city_type} areas.", "Number of orders in the {city_type} category?"],
         "SELECT COUNT(*) AS total_orders FROM orders WHERE city_type = '{city_type}'", ("city_type",)),
    make("E14", "easy", ["How many orders are there for each order type?", "Number of orders per order type.", "Count the orders of every type."],
         "SELECT order_type, COUNT(*) AS n FROM orders GROUP BY order_type ORDER BY n DESC, order_type"),
    # ---------------- medium: joins / grouping ----------------
    make("M01", "medium", ["How many orders were placed at restaurants in {city}?", "Count the orders for restaurants located in {city}.", "Total number of orders in {city}?"],
         "SELECT COUNT(*) AS total_orders FROM orders o JOIN restaurants r USING (restaurant_id) WHERE r.city_code = '{city}'", ("city",)),
    make("M02", "medium", ["What is the total revenue of restaurants in {city}?", "How much revenue did {city} restaurants make in total?", "Total order amount for the {city} area?"],
         "SELECT SUM(o.order_amount) AS total_revenue FROM orders o JOIN restaurants r USING (restaurant_id) WHERE r.city_code = '{city}'", ("city",)),
    make("M03", "medium", ["Which {n} restaurants received the most orders?", "Top {n} restaurants by number of orders.", "List the {n} busiest restaurants by order count."],
         "SELECT restaurant_id, COUNT(*) AS total_orders FROM orders GROUP BY restaurant_id ORDER BY total_orders DESC, restaurant_id LIMIT {n}", ("n",)),
    make("M04", "medium", ["What is the average delivery time for each vehicle type?", "Average delivery time per vehicle type.", "Compare delivery times across vehicle types."],
         "SELECT vehicle_type, ROUND(AVG(time_taken_min), 2) AS avg_minutes FROM deliveries GROUP BY vehicle_type ORDER BY avg_minutes DESC, vehicle_type"),
    make("M05", "medium", ["What is the average delivery time for {order_type} orders?", "How long does delivery take on average for {order_type} orders?", "Average time taken to deliver {order_type} orders?"],
         "SELECT ROUND(AVG(d.time_taken_min), 2) AS avg_minutes FROM orders o JOIN deliveries d USING (order_id) WHERE o.order_type = '{order_type}'", ("order_type",)),
    make("M06", "medium", ["What is the average order amount when the weather is {weather}?", "Average amount of orders delivered in {weather} weather?", "How much do customers spend per order in {weather} weather?"],
         "SELECT ROUND(AVG(o.order_amount), 2) AS avg_amount FROM orders o JOIN deliveries d USING (order_id) WHERE d.weather = '{weather}'", ("weather",)),
    make("M07", "medium", ["How many {payment} orders took longer than {minutes} minutes to deliver?", "Count the {payment}-paid orders delivered in more than {minutes} minutes.", "Number of slow ({minutes}+ minutes) deliveries paid by {payment}?"],
         "SELECT COUNT(*) AS n_orders FROM orders o JOIN deliveries d USING (order_id) WHERE o.payment_method = '{payment}' AND d.time_taken_min > {minutes}", ("payment", "minutes")),
    make("M08", "medium", ["What is the total spend of customers with {membership} membership?", "How much did {membership} members spend in total?", "Total order amount of {membership} customers?"],
         "SELECT SUM(o.order_amount) AS total_spent FROM orders o JOIN customers c USING (customer_id) WHERE c.membership = '{membership}'", ("membership",)),
    make("M09", "medium", ["Which {n} cities have the most orders?", "Top {n} cities by number of orders.", "List the {n} cities with the highest order counts."],
         "SELECT r.city_code, COUNT(*) AS total_orders FROM orders o JOIN restaurants r USING (restaurant_id) GROUP BY r.city_code ORDER BY total_orders DESC, r.city_code LIMIT {n}", ("n",)),
    make("M10", "medium", ["What is the average rating of riders working for restaurants in {city}?", "Average rider rating in {city}?", "How are riders in {city} rated on average?"],
         "SELECT ROUND(AVG(ri.avg_rating), 2) AS avg_rating FROM riders ri JOIN restaurants r USING (restaurant_id) WHERE r.city_code = '{city}'", ("city",)),
    make("M11", "medium", ["What is the average delivery distance for each order type?", "Average distance per order type.", "How far are deliveries on average for each type of order?"],
         "SELECT o.order_type, ROUND(AVG(d.distance_km), 2) AS avg_km FROM orders o JOIN deliveries d USING (order_id) GROUP BY o.order_type ORDER BY avg_km DESC, o.order_type"),
    make("M12", "medium", ["Which city has the most customers?", "In which city do most of our customers live?", "Find the city with the largest number of customers."],
         "SELECT city_code, COUNT(*) AS n_customers FROM customers GROUP BY city_code ORDER BY n_customers DESC, city_code LIMIT 1"),
    make("M13", "medium", ["Which orders above {amount} were paid by {payment}? Show the first {n}.", "List {n} {payment} orders worth more than {amount}.", "Show {n} orders paid with {payment} that cost over {amount}."],
         "SELECT order_id, order_amount FROM orders WHERE payment_method = '{payment}' AND order_amount > {amount} ORDER BY order_amount DESC, order_id LIMIT {n}", ("payment", "amount", "n")),
    # ---------------- hard: 3 tables, HAVING, subqueries ----------------
    make("H01", "hard", ["Which {n} restaurants in {city} have the longest average delivery time?", "Top {n} slowest restaurants in {city} by average delivery time.", "List the {n} restaurants in {city} with the highest average delivery time."],
         "SELECT o.restaurant_id, ROUND(AVG(d.time_taken_min), 2) AS avg_minutes FROM orders o JOIN deliveries d USING (order_id) JOIN restaurants r USING (restaurant_id) WHERE r.city_code = '{city}' GROUP BY o.restaurant_id ORDER BY avg_minutes DESC, o.restaurant_id LIMIT {n}", ("n", "city")),
    make("H02", "hard", ["How many riders with at least 20 deliveries have an average delivery time above {minutes_avg} minutes?", "Count the riders (20+ deliveries) whose average delivery time is over {minutes_avg} minutes.", "Number of experienced riders (at least 20 deliveries) averaging more than {minutes_avg} minutes?"],
         "SELECT COUNT(*) AS n_riders FROM (SELECT o.rider_id FROM orders o JOIN deliveries d USING (order_id) GROUP BY o.rider_id HAVING COUNT(*) >= 20 AND AVG(d.time_taken_min) > {minutes_avg}) t", ("minutes_avg",)),
    make("H03", "hard", ["Which {n} cities have the highest total revenue from {payment} orders?", "Top {n} cities by revenue of {payment}-paid orders.", "List the {n} cities where {payment} orders bring in the most money."],
         "SELECT r.city_code, SUM(o.order_amount) AS revenue FROM orders o JOIN restaurants r USING (restaurant_id) WHERE o.payment_method = '{payment}' GROUP BY r.city_code ORDER BY revenue DESC, r.city_code LIMIT {n}", ("n", "payment")),
    make("H04", "hard", ["How many customers in {city} have placed more than {k} orders?", "Count the {city} customers with over {k} orders.", "Number of customers from {city} who ordered more than {k} times?"],
         "SELECT COUNT(*) AS n_customers FROM (SELECT c.customer_id FROM customers c JOIN orders o USING (customer_id) WHERE c.city_code = '{city}' GROUP BY c.customer_id HAVING COUNT(*) > {k}) t", ("city", "k")),
    make("H05", "hard", ["What is the average delivery time for {order_type} orders under each weather condition?", "Average delivery time of {order_type} orders by weather.", "For {order_type} orders, compare the average delivery time across weather conditions."],
         "SELECT d.weather, ROUND(AVG(d.time_taken_min), 2) AS avg_minutes FROM orders o JOIN deliveries d USING (order_id) WHERE o.order_type = '{order_type}' AND d.weather IS NOT NULL GROUP BY d.weather ORDER BY avg_minutes DESC, d.weather", ("order_type",)),
    make("H06", "hard", ["Which {n} restaurants have an average order amount above the overall average?", "Top {n} restaurants whose average order amount is higher than the average of all orders.", "List {n} restaurants that earn more per order than the overall average."],
         "SELECT restaurant_id, ROUND(AVG(order_amount), 2) AS avg_amount FROM orders GROUP BY restaurant_id HAVING AVG(order_amount) > (SELECT AVG(order_amount) FROM orders) ORDER BY avg_amount DESC, restaurant_id LIMIT {n}", ("n",)),
    make("H07", "hard", ["What percentage of orders in {city} were paid by {payment}?", "Share of {payment} payments among {city} orders (in percent)?", "In {city}, what fraction of orders (as a percentage) used {payment}?"],
         "SELECT ROUND(100.0 * SUM(CASE WHEN o.payment_method = '{payment}' THEN 1 ELSE 0 END) / COUNT(*), 2) AS pct FROM orders o JOIN restaurants r USING (restaurant_id) WHERE r.city_code = '{city}'", ("city", "payment")),
    make("H08", "hard", ["Which {n} customers spent the most on {order_type} orders?", "Top {n} customers by total spend on {order_type} orders.", "List the {n} biggest spenders on {order_type} orders."],
         "SELECT c.customer_id, SUM(o.order_amount) AS total_spent FROM orders o JOIN customers c USING (customer_id) WHERE o.order_type = '{order_type}' GROUP BY c.customer_id ORDER BY total_spent DESC, c.customer_id LIMIT {n}", ("n", "order_type")),
    make("H09", "hard", ["For each weather condition, how many deliveries were slower than the overall average delivery time?", "Count the deliveries slower than average for every weather condition.", "Number of above-average-duration deliveries per weather condition?"],
         "SELECT weather, COUNT(*) AS slow_deliveries FROM deliveries WHERE time_taken_min > (SELECT AVG(time_taken_min) FROM deliveries) AND weather IS NOT NULL GROUP BY weather ORDER BY slow_deliveries DESC, weather"),
    make("H10", "hard", ["What is the average order amount in {city} for each area type?", "Average order amount per area type in {city}.", "Break down the average order amount in {city} by city type."],
         "SELECT o.city_type, ROUND(AVG(o.order_amount), 2) AS avg_amount FROM orders o JOIN restaurants r USING (restaurant_id) WHERE r.city_code = '{city}' GROUP BY o.city_type ORDER BY avg_amount DESC, o.city_type", ("city",)),
    make("H11", "hard", ["Which {n} cities earn the most revenue from festival orders?", "Top {n} cities by festival-order revenue.", "List the {n} cities with the highest revenue on festival days."],
         "SELECT r.city_code, SUM(o.order_amount) AS revenue FROM orders o JOIN restaurants r USING (restaurant_id) WHERE o.festival = 'Yes' GROUP BY r.city_code ORDER BY revenue DESC, r.city_code LIMIT {n}", ("n",)),
]

# ----------------------------------------------------------------------------
# HELD-OUT TEMPLATES (test only; never used for training)
# ----------------------------------------------------------------------------
HELD_OUT_TEMPLATES = [
    make("X01", "hard", ["Which restaurant in {city} earned the highest total revenue?", "Find the top-earning restaurant in {city}.", "In {city}, which restaurant has the largest total order amount?"],
         "SELECT o.restaurant_id, SUM(o.order_amount) AS revenue FROM orders o JOIN restaurants r USING (restaurant_id) WHERE r.city_code = '{city}' GROUP BY o.restaurant_id ORDER BY revenue DESC, o.restaurant_id LIMIT 1", ("city",)),
    make("X02", "hard", ["For each city, which restaurant has the most orders?", "Show the busiest restaurant of every city.", "Find the restaurant with the highest order count in each city."],
         "WITH c AS (SELECT r.city_code, o.restaurant_id, COUNT(*) AS n, ROW_NUMBER() OVER (PARTITION BY r.city_code ORDER BY COUNT(*) DESC, o.restaurant_id) AS rk FROM orders o JOIN restaurants r USING (restaurant_id) GROUP BY r.city_code, o.restaurant_id) SELECT city_code, restaurant_id, n FROM c WHERE rk = 1 ORDER BY city_code"),
    make("X03", "hard", ["How many customers have never paid with {payment}?", "Count the customers who never used {payment} as a payment method.", "Number of customers with no {payment} order?"],
         "SELECT COUNT(*) AS n_customers FROM customers c WHERE NOT EXISTS (SELECT 1 FROM orders o WHERE o.customer_id = c.customer_id AND o.payment_method = '{payment}')", ("payment",)),
    make("X04", "hard", ["How many restaurants have never had a festival order?", "Count the restaurants without any festival-day order.", "Number of restaurants with zero orders on festivals?"],
         "SELECT COUNT(*) AS n_restaurants FROM restaurants r WHERE NOT EXISTS (SELECT 1 FROM orders o WHERE o.restaurant_id = r.restaurant_id AND o.festival = 'Yes')"),
    make("X05", "medium", ["What is the average order amount for each month?", "Average order amount per month.", "Show the monthly average order value."],
         "SELECT MONTH(order_date) AS month, ROUND(AVG(order_amount), 2) AS avg_amount FROM orders GROUP BY MONTH(order_date) ORDER BY month"),
    make("X06", "medium", ["On which day of the week are the most orders placed?", "Which weekday is the busiest?", "Find the weekday with the highest number of orders."],
         "SELECT DAYNAME(order_date) AS weekday, COUNT(*) AS n FROM orders GROUP BY DAYNAME(order_date) ORDER BY n DESC, weekday LIMIT 1"),
    make("X07", "medium", ["What percentage of deliveries happened in {traffic} traffic?", "Share of deliveries made in {traffic} traffic (percent)?", "How many percent of all deliveries took place in {traffic} traffic?"],
         "SELECT ROUND(100.0 * SUM(CASE WHEN road_traffic = '{traffic}' THEN 1 ELSE 0 END) / COUNT(*), 2) AS pct FROM deliveries", ("traffic",)),
    make("X08", "hard", ["How many riders are slower on average than the average rider of their own restaurant?", "Count the riders whose average delivery time is above the mean of their restaurant's riders.", "Number of riders slower than their restaurant's average rider?"],
         "WITH rider_avg AS (SELECT o.rider_id, o.restaurant_id, AVG(d.time_taken_min) AS avg_min FROM orders o JOIN deliveries d USING (order_id) GROUP BY o.rider_id, o.restaurant_id), rest_avg AS (SELECT restaurant_id, AVG(avg_min) AS rest_mean FROM rider_avg GROUP BY restaurant_id) SELECT COUNT(*) AS n_riders FROM rider_avg x JOIN rest_avg y USING (restaurant_id) WHERE x.avg_min > y.rest_mean"),
    make("X09", "medium", ["How many orders are placed in each hour of the day?", "Number of orders per hour.", "Show the order count for every hour of the day."],
         "SELECT EXTRACT(hour FROM order_time) AS hour, COUNT(*) AS n FROM orders WHERE order_time IS NOT NULL GROUP BY 1 ORDER BY hour"),
    make("X10", "medium", ["Which vehicle type has the longest average pickup wait?", "Find the vehicle type with the highest average pickup waiting time.", "For which vehicle type do orders wait longest before pickup, on average?"],
         "SELECT vehicle_type, ROUND(AVG(pickup_wait_min), 2) AS avg_wait FROM deliveries WHERE pickup_wait_min IS NOT NULL GROUP BY vehicle_type ORDER BY avg_wait DESC, vehicle_type LIMIT 1"),
    make("X11", "hard", ["By how many minutes is the average delivery time in Jam traffic longer than in Low traffic?", "What is the difference in average delivery time between Jam and Low traffic?", "How much slower are deliveries in Jam traffic compared with Low traffic, on average?"],
         "SELECT ROUND((SELECT AVG(time_taken_min) FROM deliveries WHERE road_traffic = 'Jam') - (SELECT AVG(time_taken_min) FROM deliveries WHERE road_traffic = 'Low'), 2) AS diff_minutes"),
    make("X12", "medium", ["Which {n} customers placed the most festival orders?", "Top {n} customers by number of festival orders.", "List the {n} customers who ordered most often on festivals."],
         "SELECT customer_id, COUNT(*) AS festival_orders FROM orders WHERE festival = 'Yes' GROUP BY customer_id ORDER BY festival_orders DESC, customer_id LIMIT {n}", ("n",)),
    make("X13", "hard", ["Which {membership} customers in {city} spent more than {amount_big} in total?", "List the {membership} members from {city} whose total spend exceeds {amount_big}.", "Find {city} customers with {membership} membership and total spend above {amount_big}."],
         "SELECT c.customer_id, SUM(o.order_amount) AS total_spent FROM customers c JOIN orders o USING (customer_id) WHERE c.city_code = '{city}' AND c.membership = '{membership}' GROUP BY c.customer_id HAVING SUM(o.order_amount) > {amount_big} ORDER BY total_spent DESC, c.customer_id", ("city", "membership", "amount_big")),
]


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------
def build_context(con):
    """Read the real values (cities, weather types, ...) from the database."""
    def values(sql):
        return [r[0] for r in con.execute(sql).fetchall() if r[0] not in (None, "")]

    return {
        "city": values("SELECT DISTINCT city_code FROM restaurants ORDER BY 1"),
        "order_type": values("SELECT DISTINCT order_type FROM orders ORDER BY 1"),
        "weather": values("SELECT DISTINCT weather FROM deliveries ORDER BY 1"),
        "traffic": values("SELECT DISTINCT road_traffic FROM deliveries ORDER BY 1"),
        "payment": values("SELECT DISTINCT payment_method FROM orders ORDER BY 1"),
        "city_type": values("SELECT DISTINCT city_type FROM orders ORDER BY 1"),
        "membership": values("SELECT DISTINCT membership FROM customers ORDER BY 1"),
        "months": values("SELECT DISTINCT MONTH(order_date) FROM orders ORDER BY 1"),
        "n": [3, 5, 10],
        "minutes": [30, 35, 40],
        "minutes_avg": [24, 26, 28],
        "rating": [4.5, 4.6, 4.7, 4.8],
        "k": [8, 10, 12],
        "amount": [500, 1000, 1500],
        "amount_big": [3000, 5000, 8000],
    }


def sample_params(names, ctx, rng):
    params = {}
    for name in names:
        if name == "month":
            m = rng.choice(ctx["months"])
            params["month_num"], params["month_name"] = m, MONTH_NAMES[m]
        else:
            params[name] = rng.choice(ctx[name])
    return params


def run_check(con, sql):
    """Execute the SQL. Returns (ok, number_of_rows_or_error_message)."""
    try:
        rows = con.execute(sql).fetchall()
    except Exception as exc:  # a bad template must be reported, not hidden
        return False, f"error: {str(exc)[:110]}"
    if not rows:
        return False, "empty result"
    if len(rows) > MAX_ROWS:
        return False, "too many rows"
    if all(v is None for v in rows[0]):
        return False, "NULL result"
    if len(rows) == 1 and len(rows[0]) == 1 and rows[0][0] == 0:
        return False, "trivial zero result"
    return True, len(rows)


def collect(templates, con, ctx, rng, problems):
    """For every template, return the list of valid, distinct SQL queries with their parameters."""
    found = {}
    for t in templates:
        seen, valid = set(), []
        draws = DRAWS_PER_TEMPLATE if t["params"] else 1
        for _ in range(draws):
            params = sample_params(t["params"], ctx, rng)
            sql = t["sql"].format(**params)
            if sql in seen:
                continue
            seen.add(sql)
            ok, info = run_check(con, sql)
            if ok:
                valid.append({"sql": sql, "params": params, "n_rows": info})
            else:
                problems[t["id"]][info] += 1
        found[t["id"]] = valid
    return found


def build_all(con, ctx, seed=SEED):
    rng = random.Random(seed)
    problems = defaultdict(Counter)
    by_id = {t["id"]: t for t in TRAIN_TEMPLATES + HELD_OUT_TEMPLATES}

    train_found = collect(TRAIN_TEMPLATES, con, ctx, rng, problems)
    held_found = collect(HELD_OUT_TEMPLATES, con, ctx, rng, problems)

    # Split the SQL of every train-family template into train SQL and test SQL.
    # A SQL string is NEVER in both sets. Templates with few distinct SQL go fully to train.
    train_items, test_pool = [], defaultdict(list)
    for tid, items in train_found.items():
        items = items[:]
        rng.shuffle(items)
        n_test = max(2, round(0.2 * len(items))) if len(items) >= 6 else 0
        for item in items[n_test:]:
            variants = rng.sample(by_id[tid]["nl"], k=min(2, len(by_id[tid]["nl"])))
            for v in variants:
                train_items.append((tid, v.format(**item["params"]), item))
        for item in items[:n_test]:
            test_pool[tid].append(item)

    rng.shuffle(train_items)
    train_items = train_items[:MAX_TRAIN]
    train_questions = {q for _, q, _ in train_items}

    test_items = []
    in_dist = []
    for tid, items in test_pool.items():
        for item in items[:IN_DIST_PER_TEMPLATE]:
            q = rng.choice(by_id[tid]["nl"]).format(**item["params"])
            if q not in train_questions:
                in_dist.append((tid, q, item, "in_dist"))
    rng.shuffle(in_dist)
    test_items += in_dist[:IN_DIST_TOTAL]
    for tid, items in held_found.items():
        for item in items[:HELD_OUT_PER_TEMPLATE]:
            q = rng.choice(by_id[tid]["nl"]).format(**item["params"])
            test_items.append((tid, q, item, "held_out"))

    train = [{"id": f"train_{i:04d}", "question": q, "sql": it["sql"], "difficulty": by_id[tid]["difficulty"],
              "template_id": tid, "split": "train", "n_rows": it["n_rows"]} for i, (tid, q, it) in enumerate(train_items)]
    test = [{"id": f"test_{i:03d}", "question": q, "sql": it["sql"], "difficulty": by_id[tid]["difficulty"],
             "template_id": tid, "split": split, "n_rows": it["n_rows"]} for i, (tid, q, it, split) in enumerate(test_items)]
    return train, test, problems


def write_jsonl(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def main():
    import duckdb  # imported here so the template logic can be tested without DuckDB

    db_file = Path.cwd() / "db" / "food_delivery.duckdb"
    con = duckdb.connect(str(db_file).replace("\\", "/"), read_only=True)
    ctx = build_context(con)
    train, test, problems = build_all(con, ctx)
    con.close()

    out_dir = Path.cwd() / "datasets" / "text2sql"
    write_jsonl(out_dir / "train.jsonl", train)
    write_jsonl(out_dir / "test.jsonl", test)

    print(f"[Done] train: {len(train)} pairs | test: {len(test)} questions")
    print("\n[Train] by difficulty:", dict(Counter(r["difficulty"] for r in train)))
    print("[Test ] by split     :", dict(Counter(r["split"] for r in test)))
    print("[Test ] by difficulty:", dict(Counter(r["difficulty"] for r in test)))

    overlap = {r["sql"] for r in train} & {r["sql"] for r in test}
    print(f"\n[Check] SQL strings found in BOTH train and test (must be 0): {len(overlap)}")

    all_ids = [t["id"] for t in TRAIN_TEMPLATES + HELD_OUT_TEMPLATES]
    used = {r["template_id"] for r in train + test}
    print("[Check] templates that produced no data:", [i for i in all_ids if i not in used] or "none")

    if problems:
        print("\n[Rejected queries by template] (look at 'error:' lines first)")
        for tid, counter in sorted(problems.items()):
            print(f"  {tid}: {dict(counter)}")

    print("\n[Samples]")
    for r in test[:3] + test[-2:]:
        print(f"  ({r['split']}, {r['difficulty']}) {r['question']}\n    {r['sql']}")


if __name__ == "__main__":
    main()
