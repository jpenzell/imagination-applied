"""
Data path configuration for AI Adoption Paradox analysis scripts.

Edit the DATA_ROOT variable below to point to the folder where you placed
the Stack Overflow Developer Survey CSVs.

Expected structure:
    <DATA_ROOT>/2025/survey_results_public.csv
    <DATA_ROOT>/2024/survey_results_public.csv
    <DATA_ROOT>/2023/survey_results_public.csv

Download data from: https://survey.stackoverflow.co/datasets
See data/README_data.md for SHA-256 checksums to verify your files.
"""

import os
from pathlib import Path

# Set STACKOVERFLOW_DATA_ROOT to use survey files stored outside this package.
# Otherwise place the files in the package's data/<year>/ folders.
DATA_ROOT = Path(
    os.environ.get(
        "STACKOVERFLOW_DATA_ROOT",
        Path(__file__).parent.parent / "data",
    )
)

CSV_2025 = DATA_ROOT / "2025" / "survey_results_public.csv"
CSV_2024 = DATA_ROOT / "2024" / "survey_results_public.csv"
CSV_2023 = DATA_ROOT / "2023" / "survey_results_public.csv"

def check_data():
    """Verify all three CSVs exist before running analysis."""
    missing = [p for p in [CSV_2025, CSV_2024, CSV_2023] if not p.exists()]
    if missing:
        raise FileNotFoundError(
            f"Missing data files:\n" +
            "\n".join(f"  {p}" for p in missing) +
            "\n\nSee data/README_data.md for download instructions."
        )
    print("Data files found:")
    for p in [CSV_2025, CSV_2024, CSV_2023]:
        size_mb = p.stat().st_size / 1_000_000
        print(f"  {p.name} ({p.parent.name})  {size_mb:.0f} MB")
