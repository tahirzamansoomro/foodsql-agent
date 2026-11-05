"""
FoodSQL-Agent  |  Sanity checks for the Gold database

Run from the repository root:
    python src/data_pipeline/check_gold.py
"""

from pathlib import Path

import duckdb

# Path to the Gold database created by build_pipeline.py
DB_FILE = Path.cwd() / "db" / "food_delivery.duckdb"

# Open the database in read-only mode so nothing can be changed by accident
con = duckdb.connect(str(DB_FILE).replace("\\", "/"), read_only=True)

checks = {
    # 1. Restaurants that ended up with no usable coordinates
    "restaurants without coordinates":
        "SELECT COUNT(*) AS n FROM restaurants WHERE latitude IS NULL OR longitude IS NULL",

    # 2. Distance sanity check: values should be a few km, not hundreds
    "distance_km summary":
        """SELECT MIN(distance_km) AS min_km,
                  ROUND(AVG(distance_km), 2) AS avg_km,
                  MAX(distance_km) AS max_km,
                  COUNT(*) - COUNT(distance_km) AS missing
           FROM deliveries""",

    # 3. Cleaned category values (no extra spaces, no 'conditions' prefix)
    "road_traffic values": "SELECT DISTINCT road_traffic FROM deliveries ORDER BY 1",
    "order_type values": "SELECT DISTINCT order_type FROM orders ORDER BY 1",
    "vehicle_type values": "SELECT DISTINCT vehicle_type FROM deliveries ORDER BY 1",
    "city_type values": "SELECT DISTINCT city_type FROM orders ORDER BY 1",

    # 4. A join across three tables (the kind of query the agent will write)
    "sample 3-table join":
        """SELECT o.order_id, r.city_code, d.time_taken_min, d.distance_km
           FROM orders o
           JOIN restaurants r USING (restaurant_id)
           JOIN deliveries d USING (order_id)
           LIMIT 5""",
}

for title, query in checks.items():
    print(f"\n--- {title} ---")
    print(con.execute(query).fetchdf())

con.close()