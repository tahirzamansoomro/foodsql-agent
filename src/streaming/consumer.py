
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

        # Add performance tracking columns to existing tables.
        connection.execute("""
            ALTER TABLE streaming_orders
            ADD COLUMN IF NOT EXISTS sent_at TIMESTAMPTZ
        """)

        connection.execute("""
            ALTER TABLE streaming_orders
            ADD COLUMN IF NOT EXISTS consumer_received_at TIMESTAMPTZ
        """)

    finally:
        connection.close()


def parse_timestamp(value):
    if not value:
        return None

    return datetime.fromisoformat(value)


def write_batch(rows):
    """Insert a batch into DuckDB and close the connection."""

    for attempt in range(LOCK_RETRIES):
        try:
            connection = duckdb.connect(DATABASE_PATH)

            try:
                connection.executemany("""
                    INSERT INTO streaming_orders (
                        order_id,
                        status,
                        amount,
                        event_time,
                        source,
                        sent_at,
                        consumer_received_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT (order_id) DO NOTHING
                """, rows)

            finally:
                connection.close()

            return True

        except duckdb.IOException:
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
        value_deserializer=lambda value: json.loads(
            value.decode("utf-8")
        )
    )

    print("FoodSQL Consumer connected to Kafka and DuckDB.")
    print("Streaming performance tracking enabled.")

    try:
        while True:
            records = consumer.poll(
                timeout_ms=POLL_TIMEOUT_MS,
                max_records=MAX_RECORDS
            )

            rows = []

            for _, messages in records.items():
                for message in messages:

                    # Timestamp when this consumer processes the message.
                    received_at = datetime.now().astimezone()

                    event = message.value

                    rows.append((
                        str(event["order_id"]),
                        event["status"],
                        float(event["amount"]),
                        parse_timestamp(event["event_time"]),
                        event["source"],
                        parse_timestamp(event.get("sent_at")),
                        received_at
                    ))

            if not rows:
                continue

            if write_batch(rows):
                consumer.commit()

                print(
                    f"{len(rows)} order(s) saved to DuckDB."
                )

            else:
                print(
                    "Database busy, batch not saved. "
                    "Will retry on next poll."
                )

    except KeyboardInterrupt:
        print("\nConsumer stopped.")

    except (KafkaError, Exception) as error:
        print(f"Consumer error: {error}")

    finally:
        consumer.close()


if __name__ == "__main__":
    main()
