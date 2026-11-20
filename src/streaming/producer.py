
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import duckdb
from kafka import KafkaProducer
from kafka.errors import KafkaError


BOOTSTRAP_SERVERS = ["localhost:9092"]
TOPIC_NAME = "food-orders"
DATABASE_PATH = "db/food_delivery.duckdb"
STATE_FILE = Path("db/producer_last_order_id.txt")

EVENT_INTERVAL_SECONDS = float(
    os.getenv("FOODSQL_EVENT_INTERVAL_SECONDS", "0.1")
)
MAX_EVENTS = int(os.getenv("FOODSQL_MAX_EVENTS", "0"))


def _read_from_duckdb():
    try:
        connection = duckdb.connect(DATABASE_PATH, read_only=True)
    except duckdb.Error:
        return None

    try:
        result = connection.execute("""
            SELECT MAX(TRY_CAST(order_id AS BIGINT))
            FROM streaming_orders
        """).fetchone()
        return result[0]
    except duckdb.Error:
        return None
    finally:
        connection.close()


def _read_from_state_file():
    try:
        return int(STATE_FILE.read_text().strip())
    except (FileNotFoundError, ValueError):
        return None


def _save_state(order_id: int):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(str(order_id))


def get_next_order_id() -> int:
    db_max = _read_from_duckdb()
    file_max = _read_from_state_file()

    known = [value for value in (db_max, file_max) if value is not None]

    return max(known) + 1 if known else int(time.time())


def create_event(order_id: int) -> dict:
    now = datetime.now(timezone.utc).isoformat()

    return {
        "order_id": order_id,
        "status": "placed",
        "amount": 250.0,
        "event_time": now,
        "sent_at": now,
        "source": "simulated",
    }


def main():
    if MAX_EVENTS < 0:
        raise ValueError("FOODSQL_MAX_EVENTS cannot be negative.")

    if EVENT_INTERVAL_SECONDS < 0:
        raise ValueError("Event interval cannot be negative.")

    order_id = get_next_order_id()
    sent_count = 0
    producer = KafkaProducer(
        bootstrap_servers=BOOTSTRAP_SERVERS,
        value_serializer=lambda value: json.dumps(value).encode("utf-8"),
    )

    print("FoodSQL producer started.")
    print(f"Starting order ID: {order_id}")
    print(f"Event interval: {EVENT_INTERVAL_SECONDS} seconds")
    print(f"Maximum events: {MAX_EVENTS or 'Continuous'}")

    try:
        while MAX_EVENTS == 0 or sent_count < MAX_EVENTS:
            event = create_event(order_id)

            future = producer.send(TOPIC_NAME, value=event)
            metadata = future.get(timeout=10)

            sent_count += 1
            print(
                f"Sent {sent_count} | Order ID: {order_id} | "
                f"Topic: {metadata.topic} | "
                f"Sent at: {event['sent_at']}"
            )

            _save_state(order_id)
            order_id += 1

            if MAX_EVENTS == 0 or sent_count < MAX_EVENTS:
                time.sleep(EVENT_INTERVAL_SECONDS)

        print(f"\nBenchmark producer completed: {sent_count} events sent.")

    except KeyboardInterrupt:
        print(f"\nProducer stopped. Events sent: {sent_count}")

    except KafkaError as error:
        print(f"Kafka error: {error}")

    finally:
        producer.flush()
        producer.close()


if __name__ == "__main__":
    main()
