"""Verify the exact public survey files used for the released analysis."""

from hashlib import sha256

import pandas as pd

from config import CSV_2023, CSV_2024, CSV_2025, check_data


EXPECTED = {
    CSV_2025: (
        49_191,
        "2d1f65308877282edfb4470520eabbc08cb499118432a3dcec6a66c086aa2baa",
    ),
    CSV_2024: (
        65_437,
        "7f2c2dbf6989d00b80a7351de4bb3af4b52b21cc52d5c947891bbc4f4e5cbe49",
    ),
    CSV_2023: (
        89_184,
        "828874a3cf0fa1bbb4c3da6a87e5822b8563bbc04b21f9869479480dbcff410c",
    ),
}


def file_hash(path):
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main():
    check_data()
    failures = []
    for path, (expected_rows, expected_hash) in EXPECTED.items():
        actual_hash = file_hash(path)
        actual_rows = len(pd.read_csv(path, usecols=["ResponseId"]))
        status = "OK" if (actual_hash, actual_rows) == (expected_hash, expected_rows) else "FAIL"
        print(f"{path.parent.name}: {status}  rows={actual_rows:,}  sha256={actual_hash}")
        if status == "FAIL":
            failures.append(path)
    if failures:
        raise SystemExit("Data verification failed. Re-download the listed file(s).")
    print("All three survey files match the publication inputs.")


if __name__ == "__main__":
    main()
