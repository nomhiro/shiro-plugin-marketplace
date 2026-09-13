"""正解肢の「長さバイアス」を検出する。

LLM が問題を書くと、正解肢に根拠や仕組みの説明を書き込んでしまい、
**正解が一貫して最長の選択肢になる**。受講者は内容を読まずに「最長を選ぶ」
だけで正解できてしまい、模試の価値が失われる。

実績: CCA-F の模試2本（multiple-choice 90問）で **78% が正解＝最長**
（期待値25%）、正解肢の平均長が他選択肢の 1.2〜1.4 倍だった。

位置バイアス（shuffle_options.py）と同じ「攻略可能な偏り」であり、
シャッフルでは解消できない（長さは位置を変えても付いてくる）。
**内容の修正が必要**なので、品質ゲートとしてシャッフル前に通す。

判定:
  - 1問ごと: 選択肢の長さの散らばり（(max-min)/max）が tolerance 以内か
  - ファイル全体: 「正解＝最長」の割合が期待値 + 許容幅 以内か
    （期待値は選択肢数の逆数。4択なら 25%）

使い方:
    python check_option_balance.py <quiz.csv> [...]
    python check_option_balance.py <quiz.csv> --spread 0.30 --excess 0.15
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# 直接実行（python .../scripts/x.py）でも兄弟モジュールを解決できるようにする。
# pytest からは scripts パッケージとして import されるため、その場合は何もしない。
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts._console import safe_stdout
from scripts.validate_quiz_csv import OPTION_PAIRS, correct_indices, read_rows

# 1問の選択肢の長さの散らばりの上限（(max-min)/max）
DEFAULT_SPREAD = 0.30
# 「正解＝最長」の割合が期待値をこれ以上超えたら偏りとみなす
DEFAULT_EXCESS = 0.15


def option_lengths(row: list[str]) -> dict[int, int]:
    return {
        i + 1: len(row[opt])
        for i, (opt, _) in enumerate(OPTION_PAIRS)
        if row[opt].strip()
    }


def analyze(path) -> dict:
    rows = read_rows(path)[1:]
    per_question: list[dict] = []
    for i, row in enumerate(rows, 1):
        if len(row) != 17 or row[1].strip() != "multiple-choice":
            continue
        lengths = option_lengths(row)
        if len(lengths) < 2:
            continue
        correct = correct_indices(row[14])
        if len(correct) != 1 or not correct[0].isdigit():
            continue
        c = int(correct[0])
        if c not in lengths:
            continue
        mx, mn = max(lengths.values()), min(lengths.values())
        others = [v for k, v in lengths.items() if k != c]
        per_question.append({
            "q": i,
            "lengths": lengths,
            "correct": c,
            "spread": (mx - mn) / mx if mx else 0.0,
            "is_longest": lengths[c] == mx,
            "is_shortest": lengths[c] == mn,
            "ratio": lengths[c] / (sum(others) / len(others)) if others else 1.0,
            "n_options": len(lengths),
        })

    n = len(per_question)
    if n == 0:
        return {"n": 0, "per_question": []}

    longest = sum(1 for e in per_question if e["is_longest"])
    shortest = sum(1 for e in per_question if e["is_shortest"])
    # 期待値は選択肢数の逆数の平均（4択なら 0.25）
    expected = sum(1 / e["n_options"] for e in per_question) / n
    return {
        "n": n,
        "longest": longest,
        "shortest": shortest,
        "longest_share": longest / n,
        "shortest_share": shortest / n,
        "expected_share": expected,
        "mean_ratio": sum(e["ratio"] for e in per_question) / n,
        "per_question": per_question,
    }


def problems(result: dict, spread: float, excess: float) -> list[str]:
    if result["n"] == 0:
        return []
    out: list[str] = []
    for e in result["per_question"]:
        if e["spread"] > spread:
            out.append(
                f"Q{e['q']}: 選択肢の長さの散らばり {e['spread']:.0%} が上限 {spread:.0%} を超える "
                f"{e['lengths']}（正解 {e['correct']}）"
            )
    limit = result["expected_share"] + excess
    if result["longest_share"] > limit:
        out.append(
            f"正解が最長の割合 {result['longest_share']:.0%} が上限 {limit:.0%} を超える "
            f"（{result['longest']}/{result['n']} 問・期待値 {result['expected_share']:.0%}）"
            " - 受講者が内容を読まずに最長を選べてしまう"
        )
    if result["shortest_share"] > limit:
        out.append(
            f"正解が最短の割合 {result['shortest_share']:.0%} が上限 {limit:.0%} を超える "
            f"（{result['shortest']}/{result['n']} 問）"
        )
    return out


def main(argv: list[str]) -> int:
    safe_stdout()
    ap = argparse.ArgumentParser(description="正解肢の長さバイアスを検出する")
    ap.add_argument("csv_paths", nargs="+")
    ap.add_argument("--spread", type=float, default=DEFAULT_SPREAD,
                    help="1問の選択肢長の散らばりの上限（既定 0.30）")
    ap.add_argument("--excess", type=float, default=DEFAULT_EXCESS,
                    help="「正解＝最長」の割合が期待値を超えてよい幅（既定 0.15）")
    a = ap.parse_args(argv[1:])

    failed = False
    for target in a.csv_paths:
        result = analyze(target)
        if result["n"] == 0:
            print(f"SKIP {target}: multiple-choice がない")
            continue
        errs = problems(result, a.spread, a.excess)
        head = (
            f"{target}: MC {result['n']}問 / 正解が最長 {result['longest']}"
            f" ({result['longest_share']:.0%}, 期待 {result['expected_share']:.0%})"
            f" / 正解長は他の平均の {result['mean_ratio']:.2f} 倍"
        )
        if errs:
            failed = True
            print(f"FAIL {head}")
            for e in errs[:20]:
                print(f"  - {e}")
            if len(errs) > 20:
                print(f"  ... 他 {len(errs) - 20} 件")
        else:
            print(f"OK   {head}")

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
