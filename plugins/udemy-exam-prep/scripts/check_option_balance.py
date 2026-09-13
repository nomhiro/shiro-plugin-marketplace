"""正解肢の「長さバイアス」を検出する。

LLM が問題を書くと、正解肢に根拠や仕組みの説明を書き込んでしまい、
**正解が一貫して長い選択肢になる**。受講者は内容を読まずに「長いものを選ぶ」
だけで正解できてしまい、模試の価値が失われる。

実績: CCA-F の模試1本目（multiple-choice 45問）で、正解肢が2位の選択肢を
平均 +29%（最大 +111%）上回っていた。

位置バイアス（shuffle_options.py）と同じ「攻略可能な偏り」だが、
長さは位置を変えても付いてくるのでシャッフルでは解消できない。
**内容の修正が必要**なので、品質ゲートとしてシャッフル前に通す。

判定の中心は **margin**（正解肢が2位の選択肢をどれだけ上回るか）。
「最長かどうか」の二値では、長さがほぼ揃っている問題の統計的な同着まで
欠陥として報告してしまう（実測: 正解長が他の 1.03 倍でも 71% が「最長」になる）。
受講者が知覚できるのは差の大きさなので margin で測る。

  - 1問ごと: margin が margin_limit を超えていないか（既定 +20%）
             選択肢の長さの散らばり (max-min)/max が spread 以内か（既定 30%）
  - ファイル全体: margin の平均が mean_limit 以内か（既定 +8%）
                  margin_limit 超の問題の割合が share_limit 以内か（既定 15%）

使い方:
    python check_option_balance.py <quiz.csv> [...]
    python check_option_balance.py <quiz.csv> --margin 0.20 --mean 0.08
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
# 正解肢が2位をこれ以上上回ったら「目立って長い」= 攻略可能とみなす
DEFAULT_MARGIN = 0.20
# margin の平均の上限（0 に近いほど良い）
DEFAULT_MEAN = 0.08
# margin 超過問題の割合の上限
DEFAULT_SHARE = 0.15


def option_lengths(row: list[str]) -> dict[int, int]:
    return {
        i + 1: len(row[opt])
        for i, (opt, _) in enumerate(OPTION_PAIRS)
        if row[opt].strip()
    }


def analyze(path) -> dict:
    """multiple-choice の各問について長さの指標を出す。

    multi-select は正解が複数なので長さ比較の対象にしない。
    """
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
        second = max(others) if others else lengths[c]
        per_question.append({
            "q": i,
            "lengths": lengths,
            "correct": c,
            "spread": (mx - mn) / mx if mx else 0.0,
            # 正解肢が2位の選択肢をどれだけ上回るか。負なら最長ではない
            "margin": (lengths[c] - second) / second if second else 0.0,
            "is_longest": lengths[c] == mx,
            "is_shortest": lengths[c] == mn,
            "ratio": lengths[c] / (sum(others) / len(others)) if others else 1.0,
            "n_options": len(lengths),
        })

    n = len(per_question)
    if n == 0:
        return {"n": 0, "per_question": []}

    margins = [e["margin"] for e in per_question]
    return {
        "n": n,
        "longest": sum(1 for e in per_question if e["is_longest"]),
        "shortest": sum(1 for e in per_question if e["is_shortest"]),
        "mean_margin": sum(margins) / n,
        "max_margin": max(margins),
        "mean_ratio": sum(e["ratio"] for e in per_question) / n,
        "per_question": per_question,
    }


def problems(
    result: dict,
    spread: float = DEFAULT_SPREAD,
    margin_limit: float = DEFAULT_MARGIN,
    mean_limit: float = DEFAULT_MEAN,
    share_limit: float = DEFAULT_SHARE,
) -> list[str]:
    if result["n"] == 0:
        return []

    out: list[str] = []
    over: list[dict] = []
    for e in result["per_question"]:
        if e["margin"] > margin_limit:
            over.append(e)
            out.append(
                f"Q{e['q']}: 正解肢が2位より {e['margin']:+.0%} 長い"
                f"（上限 {margin_limit:+.0%}）{e['lengths']}（正解 {e['correct']}）"
                " - 不正解肢を具体化して長さを揃える"
            )
        elif e["spread"] > spread:
            out.append(
                f"Q{e['q']}: 選択肢の長さの散らばり {e['spread']:.0%} が"
                f"上限 {spread:.0%} を超える {e['lengths']}（正解 {e['correct']}）"
            )

    if result["mean_margin"] > mean_limit:
        out.append(
            f"margin の平均 {result['mean_margin']:+.1%} が上限 {mean_limit:+.0%} を超える"
            " - 正解肢が体系的に長い。内容を読まずに長いものを選べてしまう"
        )

    share = len(over) / result["n"]
    if share > share_limit:
        out.append(
            f"margin {margin_limit:+.0%} 超の問題が {len(over)}/{result['n']} 問"
            f"（{share:.0%}）で上限 {share_limit:.0%} を超える"
        )
    return out


def main(argv: list[str]) -> int:
    safe_stdout()
    ap = argparse.ArgumentParser(description="正解肢の長さバイアスを検出する")
    ap.add_argument("csv_paths", nargs="+")
    ap.add_argument("--spread", type=float, default=DEFAULT_SPREAD,
                    help="1問の選択肢長の散らばりの上限（既定 0.30）")
    ap.add_argument("--margin", type=float, default=DEFAULT_MARGIN,
                    help="正解肢が2位を上回ってよい割合の上限（既定 0.20）")
    ap.add_argument("--mean", type=float, default=DEFAULT_MEAN,
                    help="margin の平均の上限（既定 0.08）")
    ap.add_argument("--share", type=float, default=DEFAULT_SHARE,
                    help="margin 超過問題の割合の上限（既定 0.15）")
    a = ap.parse_args(argv[1:])

    failed = False
    for target in a.csv_paths:
        result = analyze(target)
        if result["n"] == 0:
            print(f"SKIP {target}: multiple-choice がない")
            continue
        errs = problems(result, a.spread, a.margin, a.mean, a.share)
        head = (
            f"{target}: MC {result['n']}問"
            f" / margin 平均 {result['mean_margin']:+.1%} 最大 {result['max_margin']:+.0%}"
            f" / 正解長は他の平均の {result['mean_ratio']:.2f} 倍"
            f" / 最長だった問題 {result['longest']}（参考）"
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
