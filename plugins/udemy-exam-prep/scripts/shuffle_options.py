"""選択肢の位置バイアスを消すシャッフルと正解位置分布の厳密検証。

LLM が生成した quiz.csv は正解が特定位置（特に2番目）に強く偏る。さらに
**単一固定シードは当たり外れが大きい**（実績: seed=42 が MC の 78.8% を1位置に
偏らせた）。そこで:

  (a) 原本 quiz.raw.csv を退避し、シャッフルは常に原本から行う（原本とずれたら止まる。後述）
      （quiz.csv を読んで quiz.csv に書き戻すと再ロール時に「一度混ぜた後」を
        再シャッフルしてしまい再現性が壊れる = 再シャッフルの罠）
  (b) 複数シードを走査し、正解位置が最も均等になるシードを自動選択する

期待票数は「その位置を実際に提供した問題」からのみ算出する。4択中心に5/6択が
混在しても位置5・6が誤検知にならない。

**原本と quiz.csv のずれ（raw ドリフト）では止まる。** quiz.csv を後から手直しすると
原本が古いまま残り、原本から再シャッフルすると手直しが消える（実績: ある講座で
発生）。ずれがあるときは上書きせずに FAIL し、どちらを正とするかを明示させる:

  --adopt  quiz.csv を正とする（原本を quiz.csv から作り直してからシャッフル）
  --force  原本を正とする（quiz.csv の手直しを捨てて原本からシャッフル）
  --check-drift  何も書かずにずれの有無だけを報告する（ずれがあれば exit 1）

内容の比較は選択肢の並び順に依存しない指紋で行う。**正解の集合も指紋に含める**
（`Correct Answers` だけを直した場合も手直しとして検出する）。
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


class RawDriftError(Exception):
    """quiz.csv に原本由来でない変更がある（上書きすると失われる）。"""

    def __init__(self, path: Path, raw: Path, rows: list[str]):
        self.path, self.raw, self.rows = path, raw, rows
        super().__init__(f"{path} に {raw.name} 由来でない変更があります")


def row_fingerprint(row: list[str]) -> tuple:
    """選択肢の並び順に依存しない行の指紋。

    シャッフルは行内の選択肢を並べ替えるだけなので、原本とその出力は
    この指紋が一致する。一致しなければ quiz.csv は原本に由来していない。

    **どの選択肢が正解かも指紋に含める。** 含めないと `Correct Answers` だけを
    直した手直し（正答の取り違えの修正そのもの）が「原本と同じ」と判定され、
    原本からの再シャッフルで誤った正答に戻る。
    """
    if len(row) != 17:
        return tuple(row)
    correct = {c for c in correct_indices(row[14])}
    pairs = tuple(sorted(
        (row[opt], row[exp], str(k) in correct)
        for k, (opt, exp) in enumerate(OPTION_PAIRS, 1)
        if row[opt].strip() or row[exp].strip()
    ))
    return (row[0], row[1], row[15], row[16], pairs)


def drift_rows(cur: list[list[str]], base: list[list[str]]) -> list[str]:
    """シャッフルでは説明できない差分を行ごとに列挙する（空ならずれなし）。

    行番号はヘッダーを1行目とする（他の検査と同じ数え方）。
    """
    out: list[str] = []
    if len(cur) != len(base):
        out.append(f"行数が違います（quiz.csv {len(cur) - 1} 問 / 原本 {len(base) - 1} 問）")
    for i, (a, b) in enumerate(zip(cur[1:], base[1:]), 2):
        if row_fingerprint(a) == row_fingerprint(b):
            continue
        if a[:1] != b[:1]:
            what = "問題文"
        elif len(a) == 17 and len(b) == 17 and a[15] != b[15]:
            what = "Overall Explanation"
        else:
            what = "選択肢・解説・正解"
        out.append(f"Row {i}: {what}が原本と違います（{(a[0] if a else '')[:40]}...）")
    return out


def raw_is_stale(path, raw) -> bool:
    """quiz.csv が quiz.raw.csv に由来していないなら True。"""
    return bool(drift_rows(read_rows(path), read_rows(raw)))


def ensure_raw(path, raw_path=None, adopt: bool = False, force: bool = False) -> Path:
    """原本を退避する。原本とずれていれば止める（明示されたときだけ解消する）。

    - 原本が無い: quiz.csv をそのまま原本にする
    - 原本とずれていない（quiz.csv は原本のシャッフル）: 原本を温存する
    - ずれている:
        adopt=True なら quiz.csv から原本を作り直す（`_parts` を結合し直した直後、
        または quiz.csv の手直しを正とするとき）
        force=True なら原本を温存する（quiz.csv の手直しを捨てる）
        どちらでもなければ `RawDriftError`

    旧版はずれを見つけると黙って原本を作り直していた。これは結合し直しには正しいが、
    **原本を手で直した場合はその修正を quiz.csv で上書きして消していた**。
    どちらを直したかは内容からは判定できないので、呼び出し側に選ばせる。

    実績（作り直しが必要な理由）: `_parts` の4問を差し替えて `finalize_section.py` を
    再実行したが、原本を温存したため merge の出力が古い原本から上書きされ、**3回の
    実行をまたいで差し替えが反映されなかった。その間すべての検証は OK を返した。**
    `finalize_section.py` は結合の直後なので `adopt` で呼ぶ（手直しの消失は結合前の
    `merge_parts.py` の検査が防ぐ）。
    """
    path = Path(path)
    raw = Path(raw_path) if raw_path else path.with_name("quiz.raw.csv")
    if not raw.exists():
        shutil.copyfile(path, raw)
        return raw
    drift = drift_rows(read_rows(path), read_rows(raw))
    if not drift:
        return raw
    if adopt:
        shutil.copyfile(path, raw)
        print(
            f"NOTE: {raw.name} を現在の {path.name} から作り直しました"
            f"（--adopt。ずれ {len(drift)} 件を {path.name} 側で採用）"
        )
        return raw
    if force:
        print(
            f"NOTE: --force。{path.name} の原本由来でない変更 {len(drift)} 件を捨てて"
            f" {raw.name} からシャッフルします"
        )
        return raw
    raise RawDriftError(path, raw, drift)


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
    path, seed: int | None = None, raw_path=None, max_seed: int = DEFAULT_SEED_RANGE,
    adopt: bool = False, force: bool = False,
) -> dict:
    """原本から読み、最良シード（または指定シード）でシャッフルして書き出す。

    原本とずれていれば `RawDriftError`（adopt / force で解消。`ensure_raw` 参照）。
    """
    path = Path(path)
    raw = ensure_raw(path, raw_path, adopt=adopt, force=force)
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
    g = ap.add_mutually_exclusive_group()
    g.add_argument(
        "--adopt", action="store_true",
        help="原本とずれていたら quiz.csv を正として原本を作り直す（結合し直した直後・quiz.csv を手直ししたとき）",
    )
    g.add_argument(
        "--force", action="store_true",
        help="原本とずれていても原本を正としてシャッフルする（quiz.csv の手直しは失われる）",
    )
    g.add_argument(
        "--check-drift", action="store_true",
        help="何も書かずに原本とのずれだけを報告する（ずれがあれば exit 1）",
    )
    a = ap.parse_args(argv[1:])

    if a.check_drift:
        path = Path(a.csv_path)
        raw = Path(a.raw) if a.raw else path.with_name("quiz.raw.csv")
        if not raw.exists():
            print(f"OK   {path}: 原本 {raw.name} がまだ無い（シャッフル前）")
            return 0
        drift = drift_rows(read_rows(path), read_rows(raw))
        if not drift:
            print(f"OK   {path}: {raw.name} のシャッフル以外の差分はありません")
            return 0
        print(f"WARN {path}: {raw.name} 由来でない変更が {len(drift)} 件あります（raw ドリフト）")
        for d in drift[:20]:
            print(f"  - {d}")
        print("  原本から再シャッフルすると、これらの変更は失われます。")
        return 1

    try:
        r = shuffle_file(
            a.csv_path, seed=a.seed, raw_path=a.raw, max_seed=a.max_seed,
            adopt=a.adopt, force=a.force,
        )
    except RawDriftError as e:
        print(
            f"FAIL {e.path}: {e.raw.name} 由来でない変更が {len(e.rows)} 件あります。"
            "上書きせずに停止しました（raw ドリフト）"
        )
        for d in e.rows[:20]:
            print(f"  - {d}")
        if len(e.rows) > 20:
            print(f"  ... 他 {len(e.rows) - 20} 件")
        print(f"  {e.path.name} の手直しを残す      → --adopt（原本を {e.path.name} から作り直す）")
        print(f"  {e.raw.name} を正とする（手直しを捨てる） → --force")
        return 1
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
