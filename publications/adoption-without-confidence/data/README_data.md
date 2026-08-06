# Survey data

The Stack Overflow Developer Survey CSVs are public source data but are not
redistributed in this repository.

Download the official archive files and save each as
`survey_results_public.csv`:

| Year | Official download | Local path |
|---|---|---|
| 2025 | <https://github.com/StackExchange/Survey/raw/refs/heads/main/packages/archive/2025/results.csv> | `data/2025/survey_results_public.csv` |
| 2024 | <https://github.com/StackExchange/Survey/raw/refs/heads/main/packages/archive/2024/results.csv> | `data/2024/survey_results_public.csv` |
| 2023 | <https://github.com/StackExchange/Survey/raw/refs/heads/main/packages/archive/2023/results.csv> | `data/2023/survey_results_public.csv` |

## Integrity metadata

| Year | Rows | Bytes | SHA-256 |
|---|---:|---:|---|
| 2025 | 49,191 | 140,893,245 | `2d1f65308877282edfb4470520eabbc08cb499118432a3dcec6a66c086aa2baa` |
| 2024 | 65,437 | 159,525,875 | `7f2c2dbf6989d00b80a7351de4bb3af4b52b21cc52d5c947891bbc4f4e5cbe49` |
| 2023 | 89,184 | 158,626,799 | `828874a3cf0fa1bbb4c3da6a87e5822b8563bbc04b21f9869479480dbcff410c` |

Run `python analysis/verify_data.py` after downloading. The verifier checks all
three full hashes and row counts before publication analysis.

By default, the scripts look under `data/<year>/`. To use an external data
directory, set `STACKOVERFLOW_DATA_ROOT` to the parent of the three year
folders.
