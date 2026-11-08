# Error analysis

## Qwen2.5-Coder-1.5B-Instruct_loop
- failed 51 of 81: 15 did not run, 36 ran but returned a wrong result
- templates with most failures: H04 (6), H01 (6), M13 (5), X13 (5), H10 (4), X01 (4)
- most common error messages: Binder Error: Table "T2" does not have a column named "order_amount"

 (4) | Parser Error: syntax error at or near "The"

LINE 1: The query is alre (3) | Catalog Error: Table with name payments does not exist!
Did you mean " (3)

**test_001** (in_dist, hard): Number of customers from MYS who ordered more than 12 times?
- gold: `SELECT COUNT(*) AS n_customers FROM (SELECT c.customer_id FROM customers c JOIN orders o USING (customer_id) WHERE c.city_code = 'MYS' GROUP BY c.customer_id HAVING COUNT(*) > 12) t`
- model: `SELECT COUNT(DISTINCT T1.customer_id) FROM customers AS T1 INNER JOIN orders AS T2 ON T1.customer_id = T2.customer_id GROUP BY T1.customer_id HAVING COUNT(T2.order_id) > 12`

**test_002** (in_dist, hard): Number of customers from LUDH who ordered more than 12 times?
- gold: `SELECT COUNT(*) AS n_customers FROM (SELECT c.customer_id FROM customers c JOIN orders o USING (customer_id) WHERE c.city_code = 'LUDH' GROUP BY c.customer_id HAVING COUNT(*) > 12) t`
- model: `SELECT COUNT(DISTINCT T1.customer_id) FROM orders AS T1 INNER JOIN customers AS T2 ON T1.customer_id = T2.customer_id WHERE T2.membership = 'Plus' AND T1.multiple_deliveries > 12`

**test_004** (in_dist, hard): List the 3 restaurants in INDO with the highest average delivery time.
- gold: `SELECT o.restaurant_id, ROUND(AVG(d.time_taken_min), 2) AS avg_minutes FROM orders o JOIN deliveries d USING (order_id) JOIN restaurants r USING (restaurant_id) WHERE r.city_code = 'INDO' GROUP BY o.restaurant_id ORDER BY avg_minutes DESC, o.restaurant_id LIMIT 3`
- model: `SELECT T1.restaurant_id FROM restaurants AS T1 INNER JOIN deliveries AS T2 ON T1.restaurant_id = T2.order_id WHERE T1.city_code = 'INDO' GROUP BY T1.restaurant_id ORDER BY AVG(T2.time_taken_min) DESC LIMIT 3`

**test_005** (in_dist, medium): How are riders in RANCHI rated on average?
- gold: `SELECT ROUND(AVG(ri.avg_rating), 2) AS avg_rating FROM riders ri JOIN restaurants r USING (restaurant_id) WHERE r.city_code = 'RANCHI'`
- model: `The query is already correct as it is. The error message indicates that the query contains a `SELECT` statement, which is allowed in DuckDB. If you still encounter any issues, please provide more details about the error message so that I can assist you further.`

## Qwen2.5-Coder-1.5B-Instruct_noloop
- failed 54 of 81: 24 did not run, 30 ran but returned a wrong result
- templates with most failures: H04 (6), H01 (6), M13 (5), X13 (5), H10 (4), X01 (4)
- most common error messages: Catalog Error: Table with name payments does not exist!
Did you mean " (7) | Binder Error: Referenced column "weather" not found in FROM clause!
Ca (2) | Binder Error: Referenced column "time_taken_min" not found in FROM cla (2)

**test_001** (in_dist, hard): Number of customers from MYS who ordered more than 12 times?
- gold: `SELECT COUNT(*) AS n_customers FROM (SELECT c.customer_id FROM customers c JOIN orders o USING (customer_id) WHERE c.city_code = 'MYS' GROUP BY c.customer_id HAVING COUNT(*) > 12) t`
- model: `SELECT COUNT(DISTINCT T1.customer_id) FROM customers AS T1 INNER JOIN orders AS T2 ON T1.customer_id = T2.customer_id GROUP BY T1.customer_id HAVING COUNT(T2.order_id) > 12`

**test_002** (in_dist, hard): Number of customers from LUDH who ordered more than 12 times?
- gold: `SELECT COUNT(*) AS n_customers FROM (SELECT c.customer_id FROM customers c JOIN orders o USING (customer_id) WHERE c.city_code = 'LUDH' GROUP BY c.customer_id HAVING COUNT(*) > 12) t`
- model: `SELECT COUNT(DISTINCT T1.customer_id) FROM orders AS T1 INNER JOIN customers AS T2 ON T1.customer_id = T2.customer_id WHERE T2.city_type = 'Metropolitan' AND T1.multiple_deliveries > 12`

**test_004** (in_dist, hard): List the 3 restaurants in INDO with the highest average delivery time.
- gold: `SELECT o.restaurant_id, ROUND(AVG(d.time_taken_min), 2) AS avg_minutes FROM orders o JOIN deliveries d USING (order_id) JOIN restaurants r USING (restaurant_id) WHERE r.city_code = 'INDO' GROUP BY o.restaurant_id ORDER BY avg_minutes DESC, o.restaurant_id LIMIT 3`
- model: `SELECT T1.restaurant_id FROM restaurants AS T1 INNER JOIN deliveries AS T2 ON T1.restaurant_id = T2.order_id WHERE T1.city_code = 'INDO' GROUP BY T1.restaurant_id ORDER BY AVG(T2.time_taken_min) DESC LIMIT 3`

**test_005** (in_dist, medium): How are riders in RANCHI rated on average?
- gold: `SELECT ROUND(AVG(ri.avg_rating), 2) AS avg_rating FROM riders ri JOIN restaurants r USING (restaurant_id) WHERE r.city_code = 'RANCHI'`
- model: `SELECT AVG(rider_rating) FROM riders WHERE restaurant_id = 'RANCHI'`

## Qwen2.5-Coder-1.5B-Instruct+lora_loop
- failed 16 of 81: 2 did not run, 14 ran but returned a wrong result
- templates with most failures: X13 (5), X03 (3), X02 (1), X04 (1), X05 (1), X06 (1)
- most common error messages: Binder Error: Referenced column "payment_method" not found in FROM cla (1) | Invalid Input Error: More than one row returned by a subquery used as  (1)

**test_058** (held_out, hard): For each city, which restaurant has the most orders?
- gold: `WITH c AS (SELECT r.city_code, o.restaurant_id, COUNT(*) AS n, ROW_NUMBER() OVER (PARTITION BY r.city_code ORDER BY COUNT(*) DESC, o.restaurant_id) AS rk FROM orders o JOIN restaurants r USING (restaurant_id) GROUP BY r.city_code, o.restaurant_id) SELECT city_code, restaurant_id, n FROM c WHERE rk = 1 ORDER BY city_code`
- model: `SELECT r.city_code, COUNT(*) AS total_orders FROM orders o JOIN restaurants r USING (restaurant_id) GROUP BY r.city_code ORDER BY total_orders DESC, r.city_code`

**test_059** (held_out, hard): Number of customers with no Card order?
- gold: `SELECT COUNT(*) AS n_customers FROM customers c WHERE NOT EXISTS (SELECT 1 FROM orders o WHERE o.customer_id = c.customer_id AND o.payment_method = 'Card')`
- model: `SELECT COUNT(*) AS n_customers FROM orders WHERE payment_method != 'Card'`

**test_060** (held_out, hard): Number of customers with no Wallet order?
- gold: `SELECT COUNT(*) AS n_customers FROM customers c WHERE NOT EXISTS (SELECT 1 FROM orders o WHERE o.customer_id = c.customer_id AND o.payment_method = 'Wallet')`
- model: `SELECT COUNT(*) AS n_customers FROM orders WHERE payment_method = 'Wallet' INTERSECT SELECT COUNT(*) AS n_customers FROM orders WHERE payment_method != 'Wallet'`

**test_061** (held_out, hard): Count the customers who never used Cash as a payment method.
- gold: `SELECT COUNT(*) AS n_customers FROM customers c WHERE NOT EXISTS (SELECT 1 FROM orders o WHERE o.customer_id = c.customer_id AND o.payment_method = 'Cash')`
- model: `SELECT COUNT(*) AS n_customers FROM customers WHERE payment_method <> 'Cash'`

## Qwen2.5-Coder-1.5B-Instruct+lora_noloop
- failed 16 of 81: 3 did not run, 13 ran but returned a wrong result
- templates with most failures: X13 (5), X03 (3), X02 (1), X04 (1), X05 (1), X06 (1)
- most common error messages: Binder Error: Referenced column "payment_method" not found in FROM cla (1) | Binder Error: column "order_date" must appear in the GROUP BY clause o (1) | Invalid Input Error: More than one row returned by a subquery used as  (1)

**test_058** (held_out, hard): For each city, which restaurant has the most orders?
- gold: `WITH c AS (SELECT r.city_code, o.restaurant_id, COUNT(*) AS n, ROW_NUMBER() OVER (PARTITION BY r.city_code ORDER BY COUNT(*) DESC, o.restaurant_id) AS rk FROM orders o JOIN restaurants r USING (restaurant_id) GROUP BY r.city_code, o.restaurant_id) SELECT city_code, restaurant_id, n FROM c WHERE rk = 1 ORDER BY city_code`
- model: `SELECT r.city_code, COUNT(*) AS total_orders FROM orders o JOIN restaurants r USING (restaurant_id) GROUP BY r.city_code ORDER BY total_orders DESC, r.city_code`

**test_059** (held_out, hard): Number of customers with no Card order?
- gold: `SELECT COUNT(*) AS n_customers FROM customers c WHERE NOT EXISTS (SELECT 1 FROM orders o WHERE o.customer_id = c.customer_id AND o.payment_method = 'Card')`
- model: `SELECT COUNT(*) AS n_customers FROM orders WHERE payment_method != 'Card'`

**test_060** (held_out, hard): Number of customers with no Wallet order?
- gold: `SELECT COUNT(*) AS n_customers FROM customers c WHERE NOT EXISTS (SELECT 1 FROM orders o WHERE o.customer_id = c.customer_id AND o.payment_method = 'Wallet')`
- model: `SELECT COUNT(*) AS n_customers FROM orders WHERE payment_method = 'Wallet' INTERSECT SELECT COUNT(*) AS n_customers FROM orders WHERE payment_method != 'Wallet'`

**test_061** (held_out, hard): Count the customers who never used Cash as a payment method.
- gold: `SELECT COUNT(*) AS n_customers FROM customers c WHERE NOT EXISTS (SELECT 1 FROM orders o WHERE o.customer_id = c.customer_id AND o.payment_method = 'Cash')`
- model: `SELECT COUNT(*) AS n_customers FROM customers WHERE payment_method != 'Cash'`
