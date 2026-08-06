# Denominator reconciliation

The released trend is descriptive context, not a longitudinal panel.

## CSV file identifiers

| Year | SHA-256 | Bytes | Rows |
|---|---|---:|---:|
| 2025 | `2d1f65308877282edfb4470520eabbc08cb499118432a3dcec6a66c086aa2baa` | 140,893,245 | 49,191 |
| 2024 | `7f2c2dbf6989d00b80a7351de4bb3af4b52b21cc52d5c947891bbc4f4e5cbe49` | 159,525,875 | 65,437 |
| 2023 | `828874a3cf0fa1bbb4c3da6a87e5822b8563bbc04b21f9869479480dbcff410c` | 158,626,799 | 89,184 |

## 2025 analytic flow

| Denominator | n | Share of reference |
|---|---:|---:|
| Public CSV rows | 49,191 | 100.0% of CSV |
| Answered `AISelect` | 33,720 | 68.5% of CSV |
| Complete `AISelect`, `AISent`, and `AIAcc` | 33,231 | 67.6% of CSV |
| Current users in complete cases | 26,102 | 78.5% of complete cases |
| Professional developers in complete cases | 25,698 | 77.3% of complete cases |
| Professional current users | 20,760 | 79.5% of primary sample |

The primary analysis uses the 26,102 current users. The full 33,231
complete-case sample is a sensitivity analysis.

## Public-results and CSV counts

| Denominator | SO published | CSV | Treatment |
|---|---:|---:|---|
| 2025 total responses | 49,009 | 49,191 | CSV is the reproducible source; note the 182-row version gap. |
| 2025 `AISelect` respondents | 33,662 | 33,720 | Analytic flow uses the CSV count. |
| 2025 professional developers | 37,356 | 37,467 | Composition context only. |
| 2025 professional developers answering `AISelect` | 26,004 | 26,045 | Context only. |
| 2024 total responses | 65,437 | 65,437 | Match. |
| 2023 total responses | 89,184 | 89,184 | Match. |

The public documentation does not establish the cause of the count
differences, so the release calls them version gaps rather than asserting a
specific filtering mechanism.

## Trust-routing shift

| Year | Trust field | Harmonized population | n | High trust | High distrust |
|---|---|---|---:|---:|---:|
| 2023 | `AIBen` | Current users | 38,888 | 48.2% | 24.2% |
| 2024 | `AIAcc` | Current users | 37,302 | 43.0% | 30.4% |
| 2025 | `AIAcc` | Current users | 26,126 | 39.3% | 37.3% |
| 2025 | `AIAcc` | All `AISelect` respondents | 33,297 | 32.8% | 45.7% |
| 2025 | `AIAcc` | Non-users only | 7,171 | 8.9% | 76.5% |

The direction of the 2024-to-2025 decline is robust, but the magnitude depends
substantially on the denominator. The publication uses the harmonized
current-user series.

## `AISelect` response rates

| Year | Total rows | `AISelect` answered | Rate |
|---|---:|---:|---:|
| 2023 | 89,184 | 87,973 | 98.6% |
| 2024 | 65,437 | 60,907 | 93.1% |
| 2025 | 49,191 | 33,720 | 68.5% |

The release does not interpret the 2025 responding subset as a population
prevalence estimate.
