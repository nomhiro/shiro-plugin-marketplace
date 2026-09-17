"""1セクション分のパイプラインを決定的な順序で通す。

6本すべてで同じ工程を繰り返すため、順序の取り違え・工程の飛ばしを防ぐ。
特に **品質ゲート（配分・重複・長さバイアス）はシャッフル前に通す**必要がある
（シャッフル後に内容修正が必要になると原本からの再シャッフルで手戻りになる）。

工程:
  1. パートを結合して quiz.csv を作る（配分・Domain 列・meta 行数を検証）
  2. CSV 整合性の検証
  2.5 解説の整合・文体・訳（正誤印 x Correct Answers など）
  3. 出典の検査（認定ページ・旧ホストの混入、出典の欠落）
  4. 正解肢の長さバイアス検出（margin。内容修正が必要なのでシャッフル前に置く）
  5. 出典 URL のロケール正規化（冪等）
  6. ドメイン配分の検証（question-bank 追記前）
  7. question-bank.md に追記
  8. 本横断の重複検証
  9. 選択肢シャッフル（原本退避 + 最良シード自動走査 + MC/MS 両方の分布検証）
 10. シャッフル後の CSV 再検証
 11. 統計レポート

使い方:
    python "${CLAUDE_PLUGIN_ROOT}/scripts/finalize_section.py" section02-mock-exam-2
    python "${CLAUDE_PLUGIN_ROOT}/scripts/finalize_section.py" section02-mock-exam-2 --check-urls
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

# 直接実行（python .../scripts/x.py）でも兄弟モジュールを解決できるようにする。
# pytest からは scripts パッケージとして import されるため、その場合は何もしない。
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# 各工程は同じ scripts/ 内のスクリプトを別プロセスで呼ぶ（工程ごとに独立させるため）
HERE = Path(__file__).resolve().parent


from scripts._console import safe_stdout  # noqa: E402
from scripts.validate_quiz_csv import read_rows  # noqa: E402


def run(label: str, argv: list[str]) -> None:
    """1工程を実行する。失敗したらそこで止める（後続工程を信用しない）。"""
    print(f"\n--- {label} ---")
    proc = subprocess.run(
        [sys.executable, *argv],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    out = (proc.stdout or "").rstrip()
    err = (proc.stderr or "").rstrip()
    if out:
        print(out)
    if proc.returncode != 0:
        if err:
            print(err)
        raise SystemExit(f"\n{label} で失敗しました（exit {proc.returncode}）。ここで停止します。")


def refresh_bank(bank: Path, section: Path) -> tuple[int, int]:
    """question-bank.md のそのセクションの行を、最新の bank-rows.md で置き換える。

    **追記ではなく貼り替えにする理由。** 旧版は「既に追記済みならスキップ」だったが、
    どちらの分岐も再実行で壊れる。

    - スキップする側: 確定後に問題を差し替えると、bank には**古い
      `tested_concept` と問題文冒頭が残り続ける**。横断の重複検査が
      実在しない問題を見ていることになる
    - 追記する側: 判定が `| section0N |` の有無なので、セクション名が
      9文字で切られる運用だと取りこぼして**同じセクションの行が二重に入る**。
      概念の再利用回数が倍になり「上限超過」の誤検出が出る

    そこで**そのセクションの既存行を全部取り除き、同じ位置に新しい行を入れる**。
    何回実行しても結果が同じになる。

    戻り値は (取り除いた行数, 入れた行数)。
    """
    rows_md = (section / "_parts" / "bank-rows.md").read_text(encoding="utf-8")
    new_rows = [l for l in rows_md.splitlines() if l.strip().startswith("|")]
    prefix = section.name.split("-")[0]          # section01 など

    def is_target(line: str) -> bool:
        cells = line.split("|")
        return (
            len(cells) >= 3
            and cells[1].strip() == prefix
            and cells[2].strip().lstrip("Q").isdigit()
        )

    out: list[str] = []
    removed = 0
    inserted = False
    for line in bank.read_text(encoding="utf-8").splitlines():
        if is_target(line):
            removed += 1
            if not inserted:
                out.extend(new_rows)
                inserted = True
            continue
        out.append(line)
    if not inserted:
        out.extend(new_rows)

    bank.write_text("\n".join(out) + "\n", encoding="utf-8", newline="\n")
    return removed, len(new_rows)


def report(section: Path, bank: Path) -> None:
    rows = read_rows(section / "quiz.csv")[1:]
    bank_rows = [
        [c.strip() for c in l.strip("| ").split(" | ")]
        for l in (section / "_parts" / "bank-rows.md").read_text(encoding="utf-8").splitlines()
        if l.startswith("|")
    ]
    print(f"\n--- 統計 ({section.name}) ---")
    print(f"問題数: {len(rows)}")
    print(f"形式: {dict(Counter(r[1] for r in rows))}")
    print(f"ドメイン: {dict(Counter(r[16] for r in rows))}")
    print(f"task_statement: {dict(sorted(Counter(b[3] for b in bank_rows).items()))}")
    print(f"シナリオ: {dict(sorted(Counter(b[5] for b in bank_rows).items()))}")
    print(f"tested_concept ユニーク: {len(set(b[4] for b in bank_rows))}/{len(bank_rows)}")
    q = [len(r[0]) for r in rows]
    e = [len(r[15]) for r in rows]
    print(f"問題文: 平均 {sum(q)//len(q)} 字 ({min(q)}-{max(q)})")
    print(f"Overall Explanation: 平均 {sum(e)//len(e)} 字 ({min(e)}-{max(e)})")
    # 表のヘッダー行（`| section | q# | ...`）を数えないよう、
    # section の直後が数字である行だけを数える。
    total_bank = sum(1 for l in bank.read_text(encoding="utf-8").splitlines()
                     if re.match(r"\| section\d", l))
    print(f"question-bank.md 累計: {total_bank} 行")


def main(argv: list[str]) -> int:
    safe_stdout()
    ap = argparse.ArgumentParser(description="1セクション分のパイプラインを通す")
    ap.add_argument("section")
    ap.add_argument("--sections", default="sections.md")
    ap.add_argument("--bank", default="question-bank.md")
    ap.add_argument("--max-seed", type=int, default=2000)
    ap.add_argument(
        "--check-urls", action="store_true",
        help="出典 URL に実際にアクセスして 200 を確認する（時間がかかる）",
    )
    a = ap.parse_args(argv[1:])

    section = Path(a.section)
    quiz = str(section / "quiz.csv")
    bank = Path(a.bank)

    run("1. パートの結合", [str(HERE / "merge_parts.py"), a.section,
                           "--sections", a.sections, "--keep-parts"])
    run("2. CSV 整合性", [str(HERE / "validate_quiz_csv.py"), quiz])
    # 形式検証では検出できない欠陥（正解番号が誤答肢を指している・訳の欠落・
    # 文体の混在・出典 URL の詰め書き）をここで落とす。内容修正を伴うため
    # シャッフルより前に置く。front matter に style が無ければ自動でスキップ。
    run("2.5 解説の整合・文体・訳",
        [str(HERE / "check_style.py"), quiz, "--sections", a.sections])

    src_argv = [str(HERE / "check_sources.py"), quiz, "--sections", a.sections]
    if a.check_urls:
        src_argv.append("--check-urls")
    run("3. 出典の検査", src_argv)

    run("4. 正解肢の長さバイアス（margin）",
        [str(HERE / "check_option_balance.py"), quiz])
    run("5. 出典 URL の正規化", [str(HERE / "normalize_urls.py"), quiz])
    run("6. ドメイン配分（question-bank 追記前）",
        [str(HERE / "validate_exam.py"), "--sections", a.sections, quiz])

    print("\n--- 7. question-bank.md の反映（貼り替え） ---")
    removed, added = refresh_bank(bank, section)
    if removed:
        print(f"{section.name.split('-')[0]} の行を {removed} 行 → {added} 行に貼り替えました")
    else:
        print(f"{added} 行を追加しました")

    run("8. 本横断の重複検証",
        [str(HERE / "validate_exam.py"), "--sections", a.sections,
         "--bank", str(bank), quiz])
    run("9. 選択肢シャッフル",
        [str(HERE / "shuffle_options.py"), quiz, "--max-seed", str(a.max_seed)])
    run("10. シャッフル後の CSV 再検証", [str(HERE / "validate_quiz_csv.py"), quiz])

    report(section, bank)
    print(f"\nOK: {section.name} のパイプラインを完了しました")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
