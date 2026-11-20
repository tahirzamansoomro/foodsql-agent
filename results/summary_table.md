# FoodSQL-Agent — Final Evaluation Summary

The two Text-to-SQL experiments use separate datasets and prompt versions.
Their accuracy results must be interpreted independently.

| Experiment | Questions | Correct | Execution Accuracy (%) | Valid SQL Rate (%) | Average Latency (s) | Average Attempts | Total API Cost ($) |
|---|---|---|---|---|---|---|---|
| Main Benchmark — Prompt V5 | 81 | 81 | 100.0 | 100.0 | 4.62 | 1.01 | 0.0725 |
| Independent Robustness — Prompt V8 | 20 | 17 | 85.0 | 100.0 | 1.66 | 1.0 | 0.0211 |

## Difficulty-wise Results

### Main Benchmark — Prompt V5

| Difficulty | Questions | Correct | Accuracy |
|---|---:|---:|---:|
| Easy | 6 | 6 | 100.0% |
| Medium | 32 | 32 | 100.0% |
| Hard | 43 | 43 | 100.0% |

### Independent Robustness — Prompt V8

| Difficulty | Questions | Correct | Accuracy |
|---|---:|---:|---:|
| Easy | 2 | 2 | 100.0% |
| Medium | 15 | 14 | 93.3% |
| Hard | 3 | 1 | 33.3% |

