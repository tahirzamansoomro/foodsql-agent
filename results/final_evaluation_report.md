# FoodSQL-Agent: Experimental Evaluation

## 1. Evaluation Overview

FoodSQL-Agent was evaluated across two Text-to-SQL experiments and one controlled Kafka streaming experiment. The evaluation examined execution accuracy, SQL validity, response latency, API cost, and streaming performance.

The two Text-to-SQL datasets are reported separately because they represent different test sets and prompt versions.

## 2. Main Text-to-SQL Benchmark — Prompt V5

**Evaluation file:** `gemini_full_prompt_v5.json`

| Metric | Result |
|---|---:|
| Total questions | 81 |
| Execution accuracy | 100% (81/81) |
| Valid SQL rate | 100% |
| Average latency | 4.62 seconds |
| Average attempts | 1.01 |
| Total API cost | $0.0725 |

### 2.1 Dataset Split Results

| Split | Questions | Execution Accuracy | Valid SQL |
|---|---:|---:|---:|
| Held-out | 28 | 100% | 100% |
| In-distribution | 53 | 100% | 100% |

### 2.2 Difficulty-Based Results

| Difficulty | Questions | Execution Accuracy |
|---|---:|---:|
| Easy | 6 | 100% |
| Medium | 32 | 100% |
| Hard | 43 | 100% |

The V5 experiment achieved 100% execution accuracy on this 81-question benchmark. The average number of attempts was 1.01, indicating that most questions were answered without requiring a repair attempt.

## 3. Independent Robustness Evaluation — Prompt V8

**Evaluation file:** `gemini_prompt_v8_robustness20.json`

| Metric | Result |
|---|---:|
| Total questions | 20 |
| Execution accuracy | 85% (17/20) |
| Valid SQL rate | 100% |
| Average latency | 1.66 seconds |
| Average attempts | 1.00 |
| Total API cost | $0.0211 |

### 3.1 Difficulty-Based Results

| Difficulty | Questions | Execution Accuracy |
|---|---:|---:|
| Easy | 2 | 100% |
| Medium | 15 | 93.3% |
| Hard | 3 | 33.3% |

Three questions failed execution-result matching despite producing valid SQL. The identified issues involved preserving NULL categories, custom distance-group ordering, and sorting category comparisons.

These failures demonstrate that syntactically valid and executable SQL does not always produce the intended answer.

## 4. Kafka Streaming Evaluation

A controlled experiment was conducted by sending 100 simulated order events through Apache Kafka and processing them with the Python consumer into DuckDB.

| Metric | Result |
|---|---:|
| Events sent | 100 |
| Events stored in DuckDB | 100 |
| Events with sent timestamps | 100 |
| Events received by consumer | 100 |
| Events with valid latency measurements | 99 |
| Negative latency samples | 1 |
| Average valid producer-to-consumer latency | 11.50 ms |
| Minimum valid latency | 2.68 ms |
| Maximum valid latency | 128.06 ms |
| Observed consumer throughput | 9.48 events/second |

One event produced a negative latency value, indicating a timestamp or clock inconsistency. It was excluded from the valid latency average but retained in the event count.

The observed throughput represents this particular controlled run, not the maximum capacity of the streaming system.

## 5. SQL Safety and Validation Testing

The SQL validation component was tested against permitted read-only queries and potentially unsafe SQL operations.

The tested policy accepted SELECT queries, including supported CTE queries, and rejected operations such as INSERT, DELETE, DROP, COPY, PRAGMA, external file-reading functions, and multiple SQL statements.

DuckDB EXPLAIN was also used to detect query planning and schema errors before execution.

These checks provide application-level safeguards; they do not constitute a complete database security guarantee.

## 6. Discussion

The main benchmark demonstrates strong performance on the 81 evaluated questions. However, the independent robustness experiment achieved 85% execution accuracy, revealing remaining weaknesses in more complex semantic and ordering requirements.

The 100% valid SQL rate in the robustness experiment shows that SQL validity and answer correctness are different evaluation dimensions.

The streaming experiment successfully stored all 100 generated events in DuckDB. Its measured average valid producer-to-consumer latency was 11.50 milliseconds, with an observed throughput of 9.48 events per second.

## 7. Limitations

1. The Text-to-SQL experiments use limited domain-specific datasets and do not establish universal Text-to-SQL accuracy.
2. The main benchmark and independent robustness test use different question sets and prompt versions; their accuracy figures should not be combined.
3. The streaming experiment uses simulated events and a local Kafka deployment, not a real commercial food-delivery platform.
4. One negative latency sample indicates a timestamp consistency issue.
5. The measured throughput is specific to the tested workload and environment.
6. Application-level SQL validation cannot guarantee semantic correctness or provide complete security isolation.
7. The cloud model's latency and cost depend on API service conditions and model availability.

## 8. Conclusion

The evaluation shows that FoodSQL-Agent successfully combines natural-language-to-SQL generation, read-only SQL validation, bounded self-correction, DuckDB analytics, and Kafka-based simulated event ingestion.

The main Text-to-SQL benchmark achieved 100% execution accuracy across 81 questions, while the independent robustness test achieved 85% across 20 questions. The controlled streaming experiment successfully stored all 100 events, with an average valid producer-to-consumer latency of 11.50 milliseconds.

Overall, the experiments demonstrate the feasibility of the proposed integrated analytics prototype while identifying areas for further improvement in semantic generalization, timestamp consistency, and broader performance testing.

