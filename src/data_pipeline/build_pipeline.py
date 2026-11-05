"""
FoodSQL-Agent  |  Step 1: Bronze -> Silver -> Gold pipeline (DuckDB)

Input  : data/raw/train.csv   (Kaggle: gauravmalik26/food-delivery-dataset)
Output : data/bronze/orders_raw.parquet      (Bronze: raw copy, no changes)
         data/silver/orders_clean.parquet    (Silver: cleaned data)
         db/food_delivery.duckdb             (Gold: restaurants, riders, orders, deliveries)

How to run (from the repository root):
    1. Place train.csv in data/raw/.
    2. pip install duckdb pandas
    3. python src/data_pipeline/build_pipeline.py
"""

from datetime import datetime
from pathlib import Path

import duckdb
import pandas as pd

# ----------------------------------------------------------------------------
# 0. Paths
# ----------------------------------------------------------------------------
# Run the script from the folder that contains the "data" directory.
ROOT = Path.cwd()
RAW_FILE = ROOT / "data" / "raw" / "train.csv"
BRONZE_FILE = ROOT / "data" / "bronze" / "orders_raw.parquet"
SILVER_FILE = ROOT / "data" / "silver" / "orders_clean.parquet"
DB_FILE = ROOT / "db" / "food_delivery.duckdb"

# Create the output folders if they do not exist yet
for p in (BRONZE_FILE, SILVER_FILE, DB_FILE):
    p.parent.mkdir(parents=True, exist_ok=True)


def sql_path(p: Path) -> str:
    """Convert Windows backslashes to forward slashes so DuckDB can read the path."""
    return str(p).replace("\\", "/")


con = duckdb.connect(sql_path(DB_FILE))

# ----------------------------------------------------------------------------
# 1. BRONZE: store the raw data as Parquet, with no transformations
# ----------------------------------------------------------------------------
# dtype=str       -> read every column as text so nothing is altered
# keep_default_na -> keep values such as "NaN " as plain text (cleaned in Silver)
raw = pd.read_csv(RAW_FILE, dtype=str, keep_default_na=False)

# Record the source file and load time (data lineage)
raw["_source_file"] = RAW_FILE.name
raw["_loaded_at"] = datetime.now().isoformat(timespec="seconds")

con.register("raw_df", raw)
con.execute(f"COPY raw_df TO '{sql_path(BRONZE_FILE)}' (FORMAT PARQUET)")
print(f"[Bronze] rows: {len(raw):,}  ->  {BRONZE_FILE.name}")

# ----------------------------------------------------------------------------
# 2. SILVER: data cleaning
# ----------------------------------------------------------------------------
# Small reusable helper functions (macros) so the same logic is not repeated.

# clean_txt: trim spaces and turn "NaN" or empty text into a real NULL
con.execute("""
CREATE OR REPLACE MACRO clean_txt(x) AS
    NULLIF(NULLIF(TRIM(x), 'NaN'), '')
""")

# to_num: convert text to a number (DOUBLE); returns NULL if it cannot be converted
con.execute("""
CREATE OR REPLACE MACRO to_num(x) AS
    TRY_CAST(clean_txt(x) AS DOUBLE)
""")

con.execute(f"""
CREATE OR REPLACE TABLE silver_orders AS
WITH c AS (
    -- Step A: clean each column and give it the correct data type
    SELECT
        clean_txt("ID")                                   AS order_id,
        clean_txt("Delivery_person_ID")                   AS rider_id,

        -- Age and rating: text to number
        CAST(to_num("Delivery_person_Age") AS INTEGER)    AS rider_age,
        to_num("Delivery_person_Ratings")                 AS rider_rating,

        -- Coordinates: some rows have a wrong minus sign
        -- (for example 22.74 and -22.74 for the same restaurant).
        -- The dataset is from India, so ABS() fixes the sign.
        -- 0 is treated as missing because (0, 0) is not a real location.
        NULLIF(ABS(to_num("Restaurant_latitude")), 0)           AS restaurant_lat,
        NULLIF(ABS(to_num("Restaurant_longitude")), 0)          AS restaurant_lon,
        NULLIF(ABS(to_num("Delivery_location_latitude")), 0)    AS delivery_lat,
        NULLIF(ABS(to_num("Delivery_location_longitude")), 0)   AS delivery_lon,

        -- Date and time: text to real DATE / TIME types
        CAST(TRY_STRPTIME(clean_txt("Order_Date"), '%d-%m-%Y') AS DATE) AS order_date,
        TRY_CAST(clean_txt("Time_Orderd") AS TIME)                      AS order_time,
        TRY_CAST(clean_txt("Time_Order_picked") AS TIME)                AS pickup_time,

        -- Weather: remove the redundant prefix in values like "conditions Sunny"
        clean_txt(REPLACE("Weatherconditions", 'conditions ', ''))      AS weather,

        clean_txt("Road_traffic_density")                 AS road_traffic,
        CAST(to_num("Vehicle_condition") AS INTEGER)      AS vehicle_condition,
        clean_txt("Type_of_order")                        AS order_type,
        clean_txt("Type_of_vehicle")                      AS vehicle_type,
        CAST(to_num("multiple_deliveries") AS INTEGER)    AS multiple_deliveries,
        clean_txt("Festival")                             AS festival,

        -- City type: fix the spelling (Metropolitian -> Metropolitan)
        REPLACE(clean_txt("City"), 'Metropolitian', 'Metropolitan')     AS city_type,

        -- Time taken: extract only the number from text like "(min) 24"
        TRY_CAST(
            NULLIF(REGEXP_REPLACE("Time_taken(min)", '[^0-9]', '', 'g'), '')
            AS INTEGER)                                   AS time_taken_min
    FROM read_parquet('{sql_path(BRONZE_FILE)}')
),
d AS (
    -- Step B: derive new columns
    SELECT
        c.*,
        -- A rider ID such as "INDORES13DEL02" contains the restaurant ("INDORES13")
        -- followed by the rider number ("DEL02"). Removing "DEL.." gives restaurant_id.
        REGEXP_REPLACE(rider_id, 'DEL[0-9]+$', '')                      AS restaurant_id
    FROM c
)
SELECT
    order_id,
    rider_id,
    restaurant_id,
    -- City code (INDO, BANG, JAP, ...) taken from the start of restaurant_id
    REGEXP_EXTRACT(restaurant_id, '^([A-Z]+)RES[0-9]+$', 1)             AS city_code,
    city_type,
    rider_age,
    rider_rating,
    restaurant_lat,
    restaurant_lon,
    delivery_lat,
    delivery_lon,
    order_date,
    order_time,
    pickup_time,

    -- Minutes between ordering and pickup.
    -- "+ 1440) % 1440" prevents a wrong negative value when pickup happens after midnight.
    CASE
        WHEN order_time IS NULL OR pickup_time IS NULL THEN NULL
        ELSE (
            (EXTRACT(hour FROM pickup_time) * 60 + EXTRACT(minute FROM pickup_time))
          - (EXTRACT(hour FROM order_time)  * 60 + EXTRACT(minute FROM order_time))
          + 1440) % 1440
    END                                                                 AS pickup_wait_min,

    -- Straight-line distance in kilometers from restaurant to customer (Haversine formula)
    CASE
        WHEN restaurant_lat IS NULL OR restaurant_lon IS NULL
          OR delivery_lat   IS NULL OR delivery_lon   IS NULL THEN NULL
        ELSE ROUND(2 * 6371 * ASIN(SQRT(
              POW(SIN(RADIANS(delivery_lat - restaurant_lat) / 2), 2)
            + COS(RADIANS(restaurant_lat)) * COS(RADIANS(delivery_lat))
              * POW(SIN(RADIANS(delivery_lon - restaurant_lon) / 2), 2)
        )), 2)
    END                                                                 AS distance_km,

    weather,
    road_traffic,
    vehicle_condition,
    order_type,
    vehicle_type,
    multiple_deliveries,
    festival,
    time_taken_min
FROM d
WHERE order_id IS NOT NULL
-- Remove duplicate orders: keep only one row per order_id
QUALIFY ROW_NUMBER() OVER (PARTITION BY order_id ORDER BY order_id) = 1
""")

con.execute(f"COPY silver_orders TO '{sql_path(SILVER_FILE)}' (FORMAT PARQUET)")
n_silver = con.execute("SELECT COUNT(*) FROM silver_orders").fetchone()[0]
print(f"[Silver] rows: {n_silver:,}  ->  {SILVER_FILE.name}")

# ----------------------------------------------------------------------------
# 3. GOLD: four separate tables (the final multi-table schema)
# ----------------------------------------------------------------------------
# Note: in this dataset a rider's age and rating change from order to order
# (one rider had between 5 and 23 different ages). Therefore age and rating are
# not stored in the riders table; they are kept per delivery in the deliveries
# table. The riders table only stores the average rating.

# 3a. restaurants (440 restaurants)
# Note: city_type (Urban / Semi-Urban / Metropolitan) is NOT stored here, because
# the same restaurant has orders with different city types. It lives in orders.
con.execute("""
CREATE OR REPLACE TABLE restaurants AS
SELECT
    restaurant_id,
    ANY_VALUE(city_code)               AS city_code,
    ROUND(MEDIAN(restaurant_lat), 6)   AS latitude,        -- median reduces the effect of bad values
    ROUND(MEDIAN(restaurant_lon), 6)   AS longitude
FROM silver_orders
GROUP BY restaurant_id
""")

# 3b. riders (1,320 riders; each rider belongs to one restaurant)
con.execute("""
CREATE OR REPLACE TABLE riders AS
SELECT
    rider_id,
    ANY_VALUE(restaurant_id)           AS restaurant_id,   -- foreign key -> restaurants
    COUNT(*)                           AS total_deliveries,
    ROUND(AVG(rider_rating), 2)        AS avg_rating,
    ROUND(AVG(time_taken_min), 1)      AS avg_delivery_minutes
FROM silver_orders
GROUP BY rider_id
""")

# 3c. orders
con.execute("""
CREATE OR REPLACE TABLE orders AS
SELECT
    order_id,
    restaurant_id,                     -- foreign key -> restaurants
    rider_id,                          -- foreign key -> riders
    order_date,
    order_time,
    order_type,
    city_type,                         -- area type of the order (Urban, Semi-Urban, Metropolitan)
    festival,
    multiple_deliveries
FROM silver_orders
""")

# 3d. deliveries (details of each order's delivery)
con.execute("""
CREATE OR REPLACE TABLE deliveries AS
SELECT
    order_id,                          -- foreign key -> orders
    pickup_time,
    pickup_wait_min,
    time_taken_min,
    distance_km,
    weather,
    road_traffic,
    vehicle_type,
    vehicle_condition,
    rider_age,                         -- rider's age at the time of delivery
    rider_rating                       -- rider's rating at the time of delivery
FROM silver_orders
""")

# ----------------------------------------------------------------------------
# 4. Checks: confirm that the tables were built correctly
# ----------------------------------------------------------------------------
print("\n[Gold] tables and row counts:")
for t in ("restaurants", "riders", "orders", "deliveries"):
    n = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
    print(f"  {t:<12} {n:>7,}")

print("\n[Check] Missing (NULL) values in Silver:")
print(con.execute("""
    SELECT
        COUNT(*) - COUNT(rider_age)       AS null_age,
        COUNT(*) - COUNT(rider_rating)    AS null_rating,
        COUNT(*) - COUNT(order_time)      AS null_order_time,
        COUNT(*) - COUNT(weather)         AS null_weather,
        COUNT(*) - COUNT(road_traffic)    AS null_traffic,
        COUNT(*) - COUNT(restaurant_lat)  AS null_rest_lat,
        COUNT(*) - COUNT(time_taken_min)  AS null_time_taken
    FROM silver_orders
""").fetchdf().T)

# Sample questions that the Text-to-SQL agent will answer later
print("\n[Test 1] Top 5 restaurants by number of orders:")
print(con.execute("""
    SELECT restaurant_id, COUNT(*) AS total_orders
    FROM orders GROUP BY restaurant_id
    ORDER BY total_orders DESC LIMIT 5
""").fetchdf())

print("\n[Test 2] Average delivery time (minutes) by weather:")
print(con.execute("""
    SELECT weather, ROUND(AVG(time_taken_min), 1) AS avg_minutes
    FROM deliveries WHERE weather IS NOT NULL
    GROUP BY weather ORDER BY avg_minutes DESC
""").fetchdf())

print("\n[Test 3] 5 riders with the lowest average rating:")
print(con.execute("""
    SELECT rider_id, restaurant_id, avg_rating
    FROM riders WHERE avg_rating IS NOT NULL
    ORDER BY avg_rating ASC LIMIT 5
""").fetchdf())

con.close()
print("\nPipeline complete. Database:", DB_FILE)