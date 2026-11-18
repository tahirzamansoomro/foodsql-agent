import json
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
EVENT_INTERVAL_SECONDS = 3


def _read_from_duckdb():
    """Try to read max order_id from DuckDB. Returns None if DB is locked/unavailable."""
    try:
        connection = duckdb.connect(DATABASE_PATH, read_only=True)
    except duckdb.IOException:
        # Consumer ne file lock ki hui hai
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
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(str(order_id))
    except OSError:
        pass


def get_next_order_id() -> int:
    """
    Next order ID nikalta hai, is order mein:
    1. DuckDB (agar lock nahi hai)
    2. State file (producer ka last sent ID)
    3. Timestamp-based ID (purane IDs se hamesha bada, duplicate nahi hoga)
    """
    db_max = _read_from_duckdb()
    file_max = _read_from_state_file()

    known = [v for v in (db_max, file_max) if v is not None]
    if known:
        return max(known) + 1

    return int(time.time())


def create_event(order_id: int) -> dict:
    return {
        "order_id": order_id,
        "status": "placed",
        "amount": 250.0,
        "event_time": datetime.now(timezone.utc).isoformat(),
        "source": "simulated"
    }


def main():
    order_id = get_next_order_id()

    producer = KafkaProducer(
        bootstrap_servers=BOOTSTRAP_SERVERS,
        value_serializer=lambda value: json.dumps(value).encode("utf-8")
    )

    print("FoodSQL continuous producer started.")
    print(f"Starting order ID: {order_id}")
    print("Press Ctrl+C to stop.")

    try:
        while True:
            event = create_event(order_id)

            future = producer.send(TOPIC_NAME, value=event)
            metadata = future.get(timeout=10)

            print(
                f"Sent order {order_id} | "
                f"Topic: {metadata.topic} | "
                f"Partition: {metadata.partition}"
            )

            _save_state(order_id)
            order_id += 1
            time.sleep(EVENT_INTERVAL_SECONDS)

    except KeyboardInterrupt:
        print("\nProducer stopped.")

    except KafkaError as error:
        print(f"Kafka error: {error}")

    finally:
        producer.flush()
        producer.close()


if __name__ == "__main__":
    main()