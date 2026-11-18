
import duckdb

DATABASE_PATH = "db/food_delivery.duckdb"


def main():
    connection = duckdb.connect(DATABASE_PATH, read_only=True)

    try:
        # 1. Total Orders
        total_orders = connection.execute("""
            SELECT COUNT(*)
            FROM streaming_orders
        """).fetchone()[0]

        # 2. Total Revenue
        total_revenue = connection.execute("""
            SELECT COALESCE(SUM(amount), 0)
            FROM streaming_orders
        """).fetchone()[0]

        # 3. Average Order Value
        average_order_value = connection.execute("""
            SELECT COALESCE(AVG(amount), 0)
            FROM streaming_orders
        """).fetchone()[0]

        # 4. Order Status Summary
        status_summary = connection.execute("""
            SELECT status, COUNT(*)
            FROM streaming_orders
            GROUP BY status
            ORDER BY status
        """).fetchall()

        # 5. Latest Order Time
        latest_order_time = connection.execute("""
            SELECT MAX(event_time)
            FROM streaming_orders
        """).fetchone()[0]

        # Display Results
        print("\n===== FoodSQL Streaming Analytics =====")
        print(f"Total Orders: {total_orders}")
        print(f"Total Revenue: Rs. {total_revenue:,.2f}")
        print(f"Average Order Value: Rs. {average_order_value:,.2f}")
        print(f"Latest Order Time: {latest_order_time}")

        print("\n===== Order Status Summary =====")

        if status_summary:
            for status, count in status_summary:
                print(f"{status}: {count}")
        else:
            print("No orders found.")

    finally:
        connection.close()


if __name__ == "__main__":
    main()
