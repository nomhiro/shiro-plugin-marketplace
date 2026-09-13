"""Udemy Practice Test Bulk Upload Template v2（17カラム）の検証と安全な入出力。

1行でも形式逸脱があるとアップロードが全件失敗するため、quiz.csv を書いた直後に必ず通す。
CSV の読み書きは harness 全体でこのモジュールの read_rows / write_rows を使う。
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

# 直接実行（python .../scripts/x.py）でも兄弟モジュールを解決できるようにする。
# pytest からは scripts パッケージとして import されるため、その場合は何もしない。
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts._console import safe_stdout

HEADER = (
    "Question", "Question Type",
    "Answer Option 1", "Explanation 1",
    "Answer Option 2", "Explanation 2",
    "Answer Option 3", "Explanation 3",
    "Answer Option 4", "Explanation 4",
    "Answer Option 5", "Explanation 5",
    "Answer Option 6", "Explanation 6",
    "Correct Answers", "Overall Explanation", "Domain",
)

REQUIRED_COLS = (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 14, 15, 16)
QUESTION_TYPES = ("multiple-choice", "multi-select")
# (選択肢, 解説) のカラム番号ペア
OPTION_PAIRS = tuple((2 + i * 2, 3 + i * 2) for i in range(6))

# 長い解説を書くためフィールド長の上限を上げる
csv.field_size_limit(10_000_000)


def read_rows(path) -> list[list[str]]:
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        return list(csv.reader(f))


def write_rows(path, rows: list[list[str]]) -> None:
    with open(path, "w", encoding="utf-8", newline="") as f:
        csv.writer(f, quoting=csv.QUOTE_MINIMAL).writerows(rows)


def correct_indices(cell: str) -> list[str]:
    return [c.strip() for c in cell.split(",") if c.strip()]


def validate_csv(path) -> list[str]:
    path = Path(path)
    errors: list[str] = []

    with open(path, "rb") as f:
        if f.read(3) == b"\xef\xbb\xbf":
            errors.append("BOM detected at file head - remove it")

    rows = read_rows(path)
    if len(rows) < 2:
        errors.append("No data rows")
        return errors

    header = rows[0]
    if len(header) != 17:
        errors.append(f"Header has {len(header)} columns, expected 17")
    for i, (got, want) in enumerate(zip(header, HEADER), 1):
        if got.strip() != want:
            errors.append(f'Header col {i}: got "{got}", expected "{want}"')

    for i, row in enumerate(rows[1:], 2):
        if len(row) != 17:
            errors.append(f"Row {i}: has {len(row)} columns, expected 17")
            continue

        qt = row[1].strip()
        if qt not in QUESTION_TYPES:
            errors.append(f'Row {i}: invalid Question Type "{qt}"')

        nopt = sum(1 for opt, _ in OPTION_PAIRS if row[opt].strip())
        correct = correct_indices(row[14])

        if qt == "multiple-choice" and len(correct) != 1:
            errors.append(
                f"Row {i}: multiple-choice with {len(correct)} correct answers "
                "- must be exactly 1"
            )
        if qt == "multi-select" and len(correct) < 2:
            errors.append(
                f"Row {i}: multi-select with {len(correct)} correct answer(s) "
                "- must be >=2 or change to multiple-choice"
            )
        if qt == "multi-select" and correct and len(correct) >= nopt:
            errors.append(
                f"Row {i}: multi-select with no distractor - {len(correct)} correct "
                f"of {nopt} options (need at least 1 incorrect)"
            )
        for c in correct:
            if not c.isdigit() or not (1 <= int(c) <= nopt):
                errors.append(
                    f'Row {i}: correct answer "{c}" out of range '
                    f"- only {nopt} option(s) present"
                )

        for col in REQUIRED_COLS:
            if not row[col].strip():
                errors.append(f"Row {i}: column {col + 1} is empty (required)")

        for opt, exp in OPTION_PAIRS:
            if bool(row[opt].strip()) != bool(row[exp].strip()):
                errors.append(
                    f"Row {i}: broken option/explanation pair at columns "
                    f"{opt + 1}/{exp + 1}"
                )

    return errors


def main(argv: list[str]) -> int:
    safe_stdout()
    if len(argv) < 2:
        print("usage: validate_quiz_csv.py <quiz.csv> [...]", file=sys.stderr)
        return 2
    failed = False
    for target in argv[1:]:
        errors = validate_csv(target)
        if errors:
            failed = True
            print(f"FAIL {target}: {len(errors)} error(s)")
            for e in errors[:20]:
                print(f"  - {e}")
            if len(errors) > 20:
                print(f"  ... and {len(errors) - 20} more")
        else:
            n = len(read_rows(target)) - 1
            print(f"OK   {target}: {n} questions, all valid")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
