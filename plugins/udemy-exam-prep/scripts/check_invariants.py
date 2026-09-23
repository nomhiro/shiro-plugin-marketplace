"""quiz.csv の文面修正の前後で、変えてはいけないものが変わっていないかを検査する。

精読レビュー（[[review-section]]）では、訳語・翻訳調・表記ゆれを直すために
全問の文面を書き換える。書き換えるのは文章だけで、**正解・配分・出典は
1つも動かしてはいけない**。ところが修正エージェントは「ついでに」選択肢を
消したり、出典 URL を別ページに差し替えたり、解説の正誤印を落としたりする。
validate_quiz_csv.py は形式しか見ないので、形式を保った改変はすべて通る。

実績: ある講座で6本300問の文面修正（約400件）を並列エージェントで行い、
修正後にこの不変条件を機械検査して、修正前後の差分が文章だけであることを確かめた。

比較元（修正前）と比較先（修正後）の各行について次を検査する:
  1. 行数とヘッダーが同じ
  2. Question Type / Correct Answers / Domain 列が同じ
  3. 空でない選択肢の番号の集合が同じ（選択肢の追加・削除がない）
  4. 各行に含まれる出典 URL の集合が同じ
  5. 各 Explanation N の冒頭の正誤印が N in Correct Answers と整合する
     （優先順: --correct-mark / --incorrect-mark → front matter の
     style.explanation_markers（いずれも完全な先頭一致）→ どちらも無ければ
     check_style.py と同じ緩い既定（先頭が「正解」/「不正解」、英語なら
     Correct / Incorrect。「不正解。」「不正解です。」のどちらも通す）。
     既定の判定では印が1件も無いファイルは検査しない。
     --no-verdict または `explanation_markers: false` で省略）

     正誤印の判定は check_style.py と共通（`marker_rule` / `read_verdict`）。
     旧版はここだけ「正解です。」「不正解です。」の完全一致を既定にしていて、
     check_style.py が通した解説をこちらが落とす食い違いがあった。

比較元の指定:
  - 既定は git の HEAD（`--ref` で変更）。修正前の状態をコミットしてから直すこと
  - git 管理外なら `--base` で修正前の CSV を直接指定する（CSV は1つだけ）

1問ずつの全カラム出力（精読用）:
  - `--show 12` / `--show 1-10,15` / `--show all` で、指定した問題の全カラムを
    カラム名つきで出力する（検査はしない）

使い方:
    python check_invariants.py section01-drill-1/quiz.csv
    python check_invariants.py section0*/quiz.csv --ref HEAD~1 --sections sections.md
    python check_invariants.py fixed/quiz.csv --base backup/quiz.orig.csv
    python check_invariants.py section01-drill-1/quiz.csv --show 1-5
"""
from __future__ import annotations

import argparse
import csv
import io
import re
import subprocess
import sys
from pathlib import Path

# 直接実行（python .../scripts/x.py）でも兄弟モジュールを解決できるようにする。
# pytest からは scripts パッケージとして import されるため、その場合は何もしない。
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# validate_quiz_csv を import すると csv.field_size_limit も引き上がる
from scripts.validate_quiz_csv import HEADER, OPTION_PAIRS, correct_indices, read_rows  # noqa: E402
from scripts.check_sources import extract_urls  # noqa: E402
from scripts.check_style import marker_rule, read_verdict  # noqa: E402
from scripts.profile import ProfileError, load_profile  # noqa: E402
from scripts._console import safe_stdout  # noqa: E402

# --correct-mark / --incorrect-mark の片方だけを指定したときの補完値
DEFAULT_CORRECT = "正解です。"
DEFAULT_INCORRECT = "不正解です。"
# style が無いときの既定（check_style.py と同じ緩い判定）
DEFAULT_RULE = marker_rule({})
# 比較する列（名前はヘッダー定義から引く）
FIXED_COLS = ("Question Type", "Correct Answers", "Domain")


class BaseUnavailable(Exception):
    """比較元の CSV が取得できない。"""


def parse_csv_text(text: str) -> list[list[str]]:
    return list(csv.reader(io.StringIO(text)))


def rows_from_git(path: Path, ref: str) -> list[list[str]]:
    """git の ref 時点の path の内容を読む。cwd に依存しないよう -C を使う。"""
    path = path.resolve()
    try:
        proc = subprocess.run(
            ["git", "-C", str(path.parent), "show", f"{ref}:./{path.name}"],
            capture_output=True,
        )
    except FileNotFoundError as e:
        raise BaseUnavailable("git が見つからない。--base で比較元を指定する") from e
    if proc.returncode != 0:
        msg = proc.stderr.decode("utf-8", "replace").strip().splitlines()
        tail = msg[-1] if msg else ""
        raise BaseUnavailable(
            f"{ref}:{path.name} を git から取得できない（{tail}）。"
            "git 管理外なら --base で比較元の CSV を指定する"
        )
    return parse_csv_text(proc.stdout.decode("utf-8-sig"))


def verdict_marks(sections_md) -> tuple[str, str] | bool | None:
    """front matter の style.explanation_markers を返す。

    (正解の印, 不正解の印) / 明示的に `explanation_markers: false` なら False /
    指定が無ければ None（呼び出し側で既定の印を使う）。
    """
    if not sections_md:
        return None
    try:
        profile = load_profile(sections_md)
    except (ProfileError, FileNotFoundError, OSError):
        return None
    style = profile.get("style")
    markers = style.get("explanation_markers") if isinstance(style, dict) else None
    if markers is False:
        return False
    if isinstance(markers, dict) and markers.get("correct") and markers.get("incorrect"):
        return str(markers["correct"]), str(markers["incorrect"])
    return None


def _urls(row: list[str]) -> set[str]:
    out: set[str] = set()
    for cell in row:
        out.update(extract_urls(cell))
    return out


def _present(row: list[str]) -> list[int]:
    return [k for k, (opt, _) in enumerate(OPTION_PAIRS, 1) if row[opt].strip()]


def _as_rule(marks) -> dict | None:
    """marks を check_style の検査規則に揃える。

    None → 検査しない / (正解の印, 不正解の印) → 完全な先頭一致 /
    規則 dict（`marker_rule` の戻り値）→ そのまま。
    """
    if marks is None:
        return None
    if isinstance(marks, dict):
        return marks
    ok, ng = marks
    return {"pairs": ((str(ok), str(ng)),), "strict": True}


def compare(old: list[list[str]], new: list[list[str]],
            marks=DEFAULT_RULE) -> list[str]:
    """不変条件の違反を返す。marks=None なら正誤印の検査を省く。

    marks は (正解の印, 不正解の印) なら完全な先頭一致、既定は check_style.py と
    同じ緩い判定（先頭が 正解 / 不正解）。
    """
    rule = _as_rule(marks)
    if rule and not rule["strict"]:
        # 既定の判定: 印を書かない運用の講座（印が1件も無い）は検査しない
        marked = any(
            read_verdict(r[exp], rule["pairs"]) is not None
            for r in new[1:] if len(r) == 17
            for opt, exp in OPTION_PAIRS if r[opt].strip()
        )
        if not marked:
            rule = None
    errs: list[str] = []
    if not old or not new:
        return ["比較元または比較先が空"]
    if [c.strip() for c in old[0]] != [c.strip() for c in new[0]]:
        errs.append("ヘッダーが変わっている")
    if len(old) != len(new):
        errs.append(f"行数が変わっている: {len(old) - 1} 問 -> {len(new) - 1} 問")
        return errs
    ix = {name: i for i, name in enumerate(HEADER)}

    for n, (o, r) in enumerate(zip(old[1:], new[1:]), 1):
        if len(o) != 17 or len(r) != 17:
            errs.append(f"Q{n}: 17カラムではない（{len(o)} -> {len(r)}）")
            continue
        for col in FIXED_COLS:
            if o[ix[col]].strip() != r[ix[col]].strip():
                errs.append(
                    f"Q{n}: {col} が変わっている: {o[ix[col]]!r} -> {r[ix[col]]!r}"
                )
        po, pn = _present(o), _present(r)
        if po != pn:
            errs.append(f"Q{n}: 空でない選択肢が変わっている: {po} -> {pn}")
        uo, un = _urls(o), _urls(r)
        if uo != un:
            gone = sorted(uo - un)
            added = sorted(un - uo)
            errs.append(f"Q{n}: 出典 URL が変わっている: 消えた {gone} / 増えた {added}")
        if rule:
            correct = {int(c) for c in correct_indices(r[ix["Correct Answers"]])
                       if c.isdigit()}
            for k in pn:
                exp = r[OPTION_PAIRS[k - 1][1]].lstrip()
                is_correct = k in correct
                if rule["strict"]:
                    ok, ng = rule["pairs"][0]
                    want = ok if is_correct else ng
                    if not exp.startswith(want):
                        errs.append(
                            f"Q{n}: Explanation {k} の冒頭が {want!r} ではない: {exp[:12]!r}"
                        )
                    continue
                got = read_verdict(exp, rule["pairs"])
                if got is None:
                    errs.append(f"Q{n}: Explanation {k} の冒頭に正誤印がない: {exp[:12]!r}")
                elif got != is_correct:
                    want = "正解" if is_correct else "不正解"
                    errs.append(
                        f"Q{n}: Explanation {k} の冒頭が{want}の印ではない: {exp[:12]!r}"
                    )
    return errs


def parse_selection(spec: str, total: int) -> list[int]:
    """'all' / '5' / '1-10,15' を 1 始まりの問題番号に展開する。"""
    if spec.strip().lower() == "all":
        return list(range(1, total + 1))
    out: list[int] = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        m = re.fullmatch(r"(\d+)\s*-\s*(\d+)", part)
        if m:
            out.extend(range(int(m.group(1)), int(m.group(2)) + 1))
        else:
            out.append(int(part))
    return [n for n in out if 1 <= n <= total]


def show(rows: list[list[str]], numbers: list[int]) -> str:
    """指定した問題の全カラムを、カラム名つきで1問ずつ並べる（精読用）。

    空の選択肢・解説は省く。Question / 選択肢 / 解説 / Overall Explanation を
    1問の中で上から順に読めるようにする（1セルずつ切り出すと、選択肢と解説の
    対応や正誤印の食い違いを見落とす）。
    """
    lines: list[str] = []
    for n in numbers:
        row = rows[n]
        lines.append(f"===== Q{n} =====")
        for ci, name in enumerate(HEADER):
            val = row[ci] if ci < len(row) else ""
            if not val.strip():
                continue
            lines.append(f"[{name}]")
            lines.append(val)
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    safe_stdout()
    ap = argparse.ArgumentParser(
        description="quiz.csv の文面修正の前後で、正解・配分・出典・正誤印が不変かを検査する"
    )
    ap.add_argument("csv_paths", nargs="+")
    ap.add_argument("--ref", default="HEAD",
                    help="比較元の git ref（既定 HEAD）")
    ap.add_argument("--base", help="比較元の CSV を直接指定する（git 管理外のとき。CSV は1つだけ）")
    ap.add_argument("--sections", default="sections.md",
                    help="正誤印（style.explanation_markers）の取得元")
    ap.add_argument("--correct-mark", default=None,
                    help="正解の解説の冒頭（完全一致。既定: front matter、無ければ先頭が「正解」）")
    ap.add_argument("--incorrect-mark", default=None,
                    help="不正解の解説の冒頭（完全一致。既定: front matter、無ければ先頭が「不正解」）")
    ap.add_argument("--no-verdict", action="store_true",
                    help="正誤印の検査を省く")
    ap.add_argument("--show", metavar="N",
                    help="検査せず、指定した問題の全カラムを出力する（例: 12 / 1-10,15 / all）")
    a = ap.parse_args(argv[1:])

    if a.show:
        for target in a.csv_paths:
            rows = read_rows(target)
            print(f"# {target}")
            print(show(rows, parse_selection(a.show, len(rows) - 1)))
        return 0

    if a.base and len(a.csv_paths) != 1:
        print("--base を使うときは CSV を1つだけ指定する", file=sys.stderr)
        return 2

    marks = None
    fm = verdict_marks(a.sections)
    if a.no_verdict:
        marks = None
    elif a.correct_mark or a.incorrect_mark:
        # CLI 指定が最優先（片方だけなら front matter、無ければ既定の文字列で補う）
        marks = (
            a.correct_mark or (fm[0] if isinstance(fm, tuple) else DEFAULT_CORRECT),
            a.incorrect_mark or (fm[1] if isinstance(fm, tuple) else DEFAULT_INCORRECT),
        )
    elif isinstance(fm, tuple):
        marks = fm
    elif fm is not False:
        marks = DEFAULT_RULE

    failed = False
    for target in a.csv_paths:
        path = Path(target)
        try:
            old = read_rows(a.base) if a.base else rows_from_git(path, a.ref)
        except (BaseUnavailable, OSError) as e:
            print(f"FAIL {target}: 比較元を読めない - {e}")
            failed = True
            continue
        new = read_rows(path)
        errs = compare(old, new, marks)
        origin = a.base or a.ref
        if errs:
            failed = True
            print(f"FAIL {target}: 不変条件の違反 {len(errs)} 件（比較元 {origin}）")
            for e in errs[:30]:
                print(f"  - {e}")
            if len(errs) > 30:
                print(f"  ... 他 {len(errs) - 30} 件")
        else:
            verdict = "・正誤印" if marks else ""
            print(f"OK   {target}: {len(new) - 1} 問。種別・正解・Domain・選択肢数・"
                  f"出典 URL{verdict}が不変（比較元 {origin}）")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
