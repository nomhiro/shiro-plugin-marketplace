"""Udemy Practice Test Bulk Upload Template v2（17カラム）の検証と安全な入出力。

1行でも形式逸脱があるとアップロードが全件失敗するため、quiz.csv を書いた直後に必ず通す。
CSV の読み書きは harness 全体でこのモジュールの read_rows / write_rows を使う。
"""
from __future__ import annotations

import csv
import re
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


# HTML タグに見える文字列の検出用。`<word>` `<word/>` `</word>` だけに当てる
# （`a < b` や `=>` のような比較・矢印は拾わない）。
HTML_TAG_RE = re.compile(r"<[A-Za-z_][A-Za-z0-9_-]*\s*/?>|</[A-Za-z_][A-Za-z0-9_-]*>")
# `<a href="https://...">...</a>` は Udemy がリンクとして保存する（実測。linkify_csv.py が作る形）。
# タグ検査の対象から外す。
ANCHOR_RE = re.compile(r'<a\s+href="https?://[^"<>]+"[^<>]*>[^<>]*</a>', re.I)
ANCHOR_TEXT_RE = re.compile(r'<a\s+href="https?://[^"<>]+"[^<>]*>([^<>]*)</a>', re.I)


# Udemy のエディタと受講画面は Markdown を解釈しない。`**強調**` は `**` が記号の
# まま表示される（実績: ある講座で82問・1,148箇所に混入した）。`**kwargs` のような
# 対にならない `**` や、`a ** b` のように前後が空白の `**` は対象外。
# 見出し `#` と行頭の `- ` `* ` も、Markdown として描画されないので同じく落とす。
MARKDOWN_RE = re.compile(
    r"(?<![A-Za-z0-9_/*])\*\*(?=\S)[^*\n]+?(?<=\S)\*\*(?![A-Za-z0-9/*_.-])"
    r"|^\s*#{1,6}\s|^\s*[-*]\s",
    re.M,
)

# 解説で選択肢を番号で参照すると、シャッフルで指す先が変わって壊れる
# （実績: 「より直接的な原因は選択肢2です」が、位置が変わると別の選択肢を指した）。
OPTION_REF_RE = re.compile(r"選択肢\s*[0-9０-９]")

# Overall Explanation の本文と出典を分ける目印
SOURCE_RE = re.compile(r"(?:\n+|(?<=\S))\s*(?:出典|参考|Sources?|References?)\s*[:：]", re.I)

# 改行の書式（警告）。空行で段落を区切り、長い解説の壁を作らない。
OVERALL_MAX_UNBROKEN = 200      # 改行なしで許す Overall Explanation 本文の長さ
LINE_MAX = 180                  # 1行（改行で区切られた単位）の長さ
OPTION_MAX_UNBROKEN = 150       # 改行なしで許す選択肢ごとの解説の長さ


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

        # セル内改行（\n）は一括取り込み時に Udemy 側で <br> に変換され、
        # 編集画面・API・学習者向け受講画面のいずれでも段落区切りとして
        # 正しく表示される（実績: CCAR-P で63問全件を検証。取り込みでの
        # 破損は再現しなかった）。読みやすさのために Explanation /
        # Overall Explanation へ意図的に \n を入れるのは問題ない。
        for ci, cell in enumerate(row, 1):
            # `<role>` のような `<単語>` 形の文字列は Udemy のサニタイザが
            # HTML タグと判定して**中身ごと削除する**。CSV としては何も
            # おかしくないので他のどの検査も通るが、投入後に選択肢の意味が
            # 消える。実績: ある講座で
            #   `Wrap the request in <role>, <context>, and <output> tags`
            # が `Wrap the request in , , and tags` になり、選択肢が
            # 解けない文になった（Explanation 側も同様に消えた）。
            # XML タグに言及したいときは括弧を外して
            # `role, context, and output XML tags` と書く。
            tags = sorted(set(HTML_TAG_RE.findall(ANCHOR_RE.sub("", cell))))
            if tags:
                errors.append(
                    f"Row {i} col {ci} ({HEADER[ci - 1]}): contains tag-like "
                    f"text {' '.join(tags)} - Udemy strips it on upload; "
                    "name the tags without angle brackets"
                )

        for ci, cell in enumerate(row, 1):
            if MARKDOWN_RE.search(cell):
                errors.append(
                    f"Row {i} col {ci} ({HEADER[ci - 1]}): contains Markdown "
                    "syntax (** / heading # / leading - *) - Udemy shows the "
                    "symbols as-is; use plain text (brackets for emphasis)"
                )
            m = OPTION_REF_RE.search(cell)
            if m:
                errors.append(
                    f"Row {i} col {ci} ({HEADER[ci - 1]}): refers to an option "
                    f"by number ({cell[m.start():m.end() + 4]}) - shuffling "
                    "changes what the number points to; describe the option"
                )

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


def layout_warnings(path) -> list[str]:
    """改行の書式の警告。FAIL にはしない（既存の講座を一括で落とさないため）。"""
    warns: list[str] = []
    rows = read_rows(path)
    for i, row in enumerate(rows[1:], 2):
        if len(row) != 17:
            continue
        for opt, exp in OPTION_PAIRS:
            text = ANCHOR_TEXT_RE.sub(r"\1", row[exp])   # リンクのマークアップは見た目の長さに入れない
            if row[opt].strip() and len(text) > OPTION_MAX_UNBROKEN and "\n" not in text:
                warns.append(
                    f"Row {i}: {HEADER[exp]} is {len(text)} chars on one line "
                    "- put the verdict on line 1 and the reason on the next"
                )
        overall = ANCHOR_TEXT_RE.sub(r"\1", row[15])
        m = SOURCE_RE.search(overall)
        body = overall[: m.start()] if m else overall
        body = body.strip("\n")
        if len(body) > OVERALL_MAX_UNBROKEN and "\n" not in body:
            warns.append(
                f"Row {i}: Overall Explanation is {len(body)} chars with no line "
                "break - separate paragraphs with a blank line"
            )
        elif any(len(line) > LINE_MAX for line in body.split("\n")):
            warns.append(
                f"Row {i}: Overall Explanation has a paragraph over {LINE_MAX} chars"
            )
        if m and m.start() > 0 and not m.group(0).startswith("\n\n"):
            warns.append(f"Row {i}: put a blank line before the source line")
    return warns


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
        warns = layout_warnings(target)
        if warns:
            print(f"WARN {target}: {len(warns)} layout warning(s) (not a failure)")
            for w in warns[:10]:
                print(f"  - {w}")
            if len(warns) > 10:
                print(f"  ... and {len(warns) - 10} more")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
