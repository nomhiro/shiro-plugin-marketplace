"""選択肢の位置バイアスを消すシャッフルと正解位置分布の厳密検証。

LLM が生成した quiz.csv は正解が特定位置（特に2番目）に強く偏る。さらに
**単一固定シードは当たり外れが大きい**（実績: seed=42 が MC の 78.8% を1位置に
偏らせた）。そこで:

  (a) 原本 quiz.raw.csv を一度だけ退避し、シャッフルは常に原本から行う
      （quiz.csv を読んで quiz.csv に書き戻すと再ロール時に「一度混ぜた後」を
        再シャッフルしてしまい再現性が壊れる = 再シャッフルの罠）
  (b) 複数シードを走査し、正解位置が最も均等になるシードを自動選択する

期待票数は「その位置を実際に提供した問題」からのみ算出する。4択中心に5/6択が
混在しても位置5・6が誤検知にならない。
"""
from __future__ import annotations

import argparse
import random
import shutil
import sys
from collections import Counter
from pathlib import Path

# 直接実行（python .../scripts/x.py）でも兄弟モジュールを解決できるようにする。
# pytest からは scripts パッケージとして import されるため、その場合は何もしない。
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts._console import safe_stdout
from scripts.validate_quiz_csv import (
    OPTION_PAIRS, correct_indices, read_rows, write_rows,
)

DEFAULT_SEED_RANGE = 500
# 相対許容（|実測-期待| / 期待）。票数が少ない位置向けに絶対許容の床も併用する
REL_TOLERANCE = 0.20
ABS_TOLERANCE_FLOOR = 1.5
# シード走査を打ち切る「十分良い」閾値（最悪相対偏差）
GOOD_ENOUGH = 0.06


def _n_options(row: list[str]) -> int:
    return sum(1 for opt, _ in OPTION_PAIRS if row[opt].strip())


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


def position_distribution(rows: list[list[str]], qtype: str = "multiple-choice") -> dict[str, int]:
    """指定タイプの正解位置のヒストグラム（キーは Correct Answers セルそのまま）。"""
    counter: Counter[str] = Counter()
    for row in rows[1:] if rows and rows[0][:1] == ["Question"] else rows:
        if len(row) == 17 and row[1].strip() == qtype:
            counter[row[14].strip()] += 1
    return dict(counter)


def position_balance(
    rows: list[list[str]], qtype: str = "multiple-choice"
) -> list[dict]:
    """位置ごとの実測票数と期待票数を返す。

    期待票数は「その位置を提供した問題」だけから積む:
      nopt 個の選択肢を持つ問題は、位置 1..nopt のそれぞれに ncorrect/nopt を寄与する。
    """
    body = rows[1:] if rows and rows[0][:1] == ["Question"] else rows
    actual: Counter[int] = Counter()
    expected: Counter[float] = Counter()

    for row in body:
        if len(row) != 17 or row[1].strip() != qtype:
            continue
        nopt = _n_options(row)
        correct = [int(c) for c in correct_indices(row[14]) if c.isdigit()]
        if nopt < 2 or not correct:
            continue
        share = len(correct) / nopt
        for pos in range(1, nopt + 1):
            expected[pos] += share
        for pos in correct:
            actual[pos] += 1

    out: list[dict] = []
    for pos in sorted(set(actual) | set(expected)):
        exp = expected.get(pos, 0.0)
        act = actual.get(pos, 0)
        tol = max(ABS_TOLERANCE_FLOOR, REL_TOLERANCE * exp)
        out.append({
            "position": pos,
            "actual": act,
            "expected": round(exp, 1),
            "within_tolerance": abs(act - exp) <= tol,
        })
    return out


def worst_relative_deviation(rows: list[list[str]], qtype: str = "multiple-choice") -> float:
    """指定タイプの最悪相対偏差。期待票数0の位置は無視する。"""
    worst = 0.0
    for entry in position_balance(rows, qtype):
        exp = entry["expected"]
        if exp <= 0:
            continue
        worst = max(worst, abs(entry["actual"] - exp) / exp)
    return worst


def combined_worst_deviation(rows: list[list[str]]) -> float:
    """multiple-choice と multi-select の両方を見た最悪相対偏差。

    シード選択の目的関数。MC だけを最適化すると MS に偏りが残り、
    「multi-select では選択肢1を必ず入れる」といった攻略が成立してしまう
    （実績: 15問の MS のうち11問で位置1が正解に含まれる状態が発生した）。
    """
    return max(
        worst_relative_deviation(rows, "multiple-choice"),
        worst_relative_deviation(rows, "multi-select"),
    )


def balance_warnings(rows: list[list[str]]) -> list[str]:
    warnings: list[str] = []
    for qtype in ("multiple-choice", "multi-select"):
        for entry in position_balance(rows, qtype):
            if not entry["within_tolerance"]:
                warnings.append(
                    f"{qtype} position {entry['position']}: "
                    f"actual {entry['actual']} vs expected {entry['expected']} "
                    "- outside tolerance"
                )
    return warnings


def row_fingerprint(row: list[str]) -> tuple:
    """選択肢の並び順に依存しない行の指紋。

    シャッフルは行内の選択肢を並べ替えるだけなので、原本とその出力は
    この指紋が一致する。一致しなければ quiz.csv は原本に由来していない。
    """
    pairs = tuple(sorted((row[opt], row[exp]) for opt, exp in OPTION_PAIRS))
    return (row[0], row[1], row[15], row[16], pairs)


def raw_is_stale(path, raw) -> bool:
    """quiz.csv が quiz.raw.csv に由来していないなら True。"""
    cur = read_rows(path)
    base = read_rows(raw)
    if len(cur) != len(base):
        return True
    for a, b in zip(cur[1:], base[1:]):
        if len(a) != 17 or len(b) != 17:
            if a != b:
                return True
            continue
        if row_fingerprint(a) != row_fingerprint(b):
            return True
    return False


def ensure_raw(path, raw_path=None) -> Path:
    """原本を退避する。整合しない原本は作り直す。

    既存の原本が現在の quiz.csv と**整合しない**（= quiz.csv が原本に由来しない）
    場合は原本を作り直す。作り直さないと、`_parts` を修正して結合し直した内容が
    古い原本からのシャッフルに静かに上書きされる。

    実績: `_parts` の4問を差し替えて `finalize_section.py` を再実行したが、
    原本を温存したため merge の出力が古い原本から上書きされ、**3回の実行を
    またいで差し替えが反映されなかった。その間すべての検証は OK を返した。**

    なお quiz.csv を手で編集した場合も原本は作り直される。原本の唯一の用途は
    再ロールであり、quiz.csv を再現できない原本は定義上すでに無効なため。
    """
    path = Path(path)
    raw = Path(raw_path) if raw_path else path.with_name("quiz.raw.csv")
    if not raw.exists():
        shutil.copyfile(path, raw)
        return raw
    if raw_is_stale(path, raw):
        shutil.copyfile(path, raw)
        print(
            f"NOTE: {raw.name} が現在の {path.name} と整合しないため作り直しました"
            f"（{path.name} が結合し直されたか手で編集されています）"
        )
    return raw


def _shuffled(base: list[list[str]], seed: int) -> list[list[str]]:
    rng = random.Random(seed)
    return [shuffle_row(r, rng) if len(r) == 17 else r for r in base]


def choose_seed(
    base: list[list[str]], max_seed: int = DEFAULT_SEED_RANGE
) -> tuple[int, float]:
    """正解位置が最も均等になるシードを走査して返す。

    multiple-choice と multi-select の両方を同時に見る（片方だけ最適化すると
    もう片方に攻略可能な偏りが残る）。
    """
    best_seed, best_worst = 1, float("inf")
    for seed in range(1, max_seed + 1):
        worst = combined_worst_deviation([["Question"]] + _shuffled(base, seed))
        if worst < best_worst:
            best_seed, best_worst = seed, worst
        if worst <= GOOD_ENOUGH:
            break
    return best_seed, best_worst


def shuffle_file(
    path, seed: int | None = None, raw_path=None, max_seed: int = DEFAULT_SEED_RANGE
) -> dict:
    """原本から読み、最良シード（または指定シード）でシャッフルして書き出す。"""
    path = Path(path)
    raw = ensure_raw(path, raw_path)
    rows = read_rows(raw)
    header, base = rows[0], rows[1:]

    if seed is None:
        seed, worst = choose_seed(base, max_seed=max_seed)
    else:
        worst = combined_worst_deviation([header] + _shuffled(base, seed))

    final = [header] + _shuffled(base, seed)
    write_rows(path, final)

    return {
        "n": len(final) - 1,
        "seed": seed,
        "worst_relative_deviation": round(worst, 3),
        "raw": str(raw),
        "mc_distribution": position_distribution(final, "multiple-choice"),
        "mc_balance": position_balance(final, "multiple-choice"),
        "ms_balance": position_balance(final, "multi-select"),
        "warnings": balance_warnings(final),
    }


def main(argv: list[str]) -> int:
    safe_stdout()
    ap = argparse.ArgumentParser(
        description="quiz.csv の選択肢をシャッフルし正解位置を均等化する"
    )
    ap.add_argument("csv_path")
    ap.add_argument(
        "--seed", type=int, default=None,
        help="固定シードを使う。省略時は最良シードを自動走査（推奨）",
    )
    ap.add_argument("--max-seed", type=int, default=DEFAULT_SEED_RANGE)
    ap.add_argument("--raw", default=None, help="原本のパス（既定: 同ディレクトリの quiz.raw.csv）")
    a = ap.parse_args(argv[1:])

    r = shuffle_file(a.csv_path, seed=a.seed, raw_path=a.raw, max_seed=a.max_seed)
    print(
        f"shuffled {r['n']} questions / seed={r['seed']} / "
        f"worst relative deviation={r['worst_relative_deviation']:.1%} / raw={r['raw']}"
    )
    print("multiple-choice position balance:")
    for e in r["mc_balance"]:
        mark = "OK" if e["within_tolerance"] else "CHECK"
        print(f"  position {e['position']}: actual {e['actual']} / expected {e['expected']} [{mark}]")
    if r["ms_balance"]:
        print("multi-select position balance:")
        for e in r["ms_balance"]:
            mark = "OK" if e["within_tolerance"] else "CHECK"
            print(f"  position {e['position']}: actual {e['actual']} / expected {e['expected']} [{mark}]")
    for w in r["warnings"]:
        print(f"  WARN: {w}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
