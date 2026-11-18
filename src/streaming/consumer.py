import json
import time
from datetime import datetime

import duckdb
from kafka import KafkaConsumer
from kafka.errors import KafkaError


BOOTSTRAP_SERVERS = ["localhost:9092"]
TOPIC_NAME = "food-orders"
GROUP_ID = "foodsql-duckdb-consumer-v1"
DATABASE_PATH = "db/food_delivery.duckdb"

POLL_TIMEOUT_MS = 2000
MAX_RECORDS = 50
LOCK_RETRIES = 10
LOCK_RETRY_DELAY = 0.5


def create_streaming_table():
    connection = duckdb.connect(DATABASE_PATH)
    try:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS streaming_orders (
                order_id VARCHAR PRIMARY KEY,
                status VARCHAR,
                amount DOUBLE,
                event_time TIMESTAMPTZ,
                source VARCHAR,
                ingested_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
            )
        """)
    finally:
        connection.close()


def write_batch(rows):
    """Batch insert karo, phir connection turant band karo taaki FastAPI padh sake."""
    for attempt in range(LOCK_RETRIES):
        try:
            connection = duckdb.connect(DATABASE_PATH)
            try:
                connection.executemany("""
                    INSERT INTO streaming_orders
                        (order_id, status, amount, event_time, source)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT (order_id) DO NOTHING
                """, rows)
            finally:
                connection.close()
            return True
        except duckdb.IOException:
            # FastAPI us waqt file padh rahi hai, thodi der baad dobara try karo
            time.sleep(LOCK_RETRY_DELAY)
    return False


def main():
    create_streaming_table()

    consumer = KafkaConsumer(
        TOPIC_NAME,
        bootstrap_servers=BOOTSTRAP_SERVERS,
        group_id=GROUP_ID,
        auto_offset_reset="earliest",
        enable_auto_commit=False,
        value_deserializer=lambda value: json.loads(value.decode("utf-8"))
    )

    print("FoodSQL Consumer connected to Kafka and DuckDB.")

    try:
        while True:
            records = consumer.poll(
                timeout_ms=POLL_TIMEOUT_MS,
                max_records=MAX_RECORDS
            )

            rows = []
            for _, messages in records.items():
                for message in messages:
                    event = message.value
                    rows.append((
                        str(event["order_id"]),
                        event["status"],
                        float(event["amount"]),
                        datetime.fromisoformat(event["event_time"]),
                        event["source"]
                    ))

            if not rows:
                continue

            if write_batch(rows):
                consumer.commit()
                print(f"{len(rows)} order(s) saved to DuckDB.")
            else:
                print("Database busy, batch not saved. Will retry on next poll.")

    except KeyboardInterrupt:
        print("\nConsumer stopped.")

    except (KafkaError, Exception) as error:
        print(f"Consumer error: {error}")

    finally:
        consumer.close()


if __name__ == "__main__":
    main()