"""選択肢の位置バイアスを消すための決定的シャッフルと正解位置分布の検証。

question-author は「正解を選択肢1に置きがち」なので、生成直後に必ず通す。
seed 固定なので同じ入力からは常に同じ出力になる（再実行で差分が暴れない）。
"""
from __future__ import annotations

import argparse
import random
import sys
from collections import Counter

from scripts.validate_quiz_csv import (
    OPTION_PAIRS, correct_indices, read_rows, write_rows,
)


def shuffle_row(row: list[str], rng: random.Random) -> list[str]:
    out = list(row)
    filled = [(row[o], row[e]) for o, e in OPTION_PAIRS if row[o].strip()]
    n = len(filled)
    if n < 2:
        return out

    correct_old = {int(c) for c in correct_indices(row[14]) if c.isdigit()}
    order = list(range(n))
    rng.shuffle(order)

    for new_pos, old_pos in enumerate(order):
        opt_col, exp_col = OPTION_PAIRS[new_pos]
        out[opt_col], out[exp_col] = filled[old_pos]
    for pos in range(n, len(OPTION_PAIRS)):
        opt_col, exp_col = OPTION_PAIRS[pos]
        out[opt_col], out[exp_col] = "", ""

    new_correct = sorted(
        new_pos + 1 for new_pos, old_pos in enumerate(order)
        if (old_pos + 1) in correct_old
    )
    out[14] = ",".join(str(c) for c in new_correct)
    return out


def position_distribution(rows: list[list[str]]) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for row in rows[1:]:
        if len(row) == 17 and row[1].strip() == "multiple-choice":
            counter[row[14].strip()] += 1
    return dict(counter)


def distribution_warnings(
    dist: dict[str, int], n_mc: int, tolerance: float = 0.15
) -> list[str]:
    if n_mc == 0:
        return []
    positions = sorted(dist) or ["1"]
    expected = 1 / max(len(positions), 2)
    warnings: list[str] = []
    for pos in positions:
        share = dist.get(pos, 0) / n_mc
        if abs(share - expected) > tolerance:
            warnings.append(
                f"correct-answer position {pos}: {dist.get(pos, 0)}/{n_mc} "
                f"({share:.0%}) deviates from the expected {expected:.0%}"
            )
    return warnings


def shuffle_file(path, seed: int = 42) -> dict:
    rows = read_rows(path)
    rng = random.Random(seed)
    shuffled = [rows[0]] + [
        shuffle_row(r, rng) if len(r) == 17 else r for r in rows[1:]
    ]
    write_rows(path, shuffled)
    dist = position_distribution(shuffled)
    n_mc = sum(dist.values())
    return {
        "n": len(shuffled) - 1,
        "distribution": dist,
        "warnings": distribution_warnings(dist, n_mc),
    }


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(
        description="quiz.csv の選択肢を決定的にシャッフルする"
    )
    ap.add_argument("csv_path")
    ap.add_argument("--seed", type=int, default=42)
    a = ap.parse_args(argv[1:])

    result = shuffle_file(a.csv_path, seed=a.seed)
    print(f"shuffled {result['n']} questions (seed={a.seed})")
    print(f"correct-answer position distribution: {result['distribution']}")
    for w in result["warnings"]:
        print(f"  WARN: {w}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
