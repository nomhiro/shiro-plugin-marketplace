"""ドメイン別のパート CSV を1本のフル模試 quiz.csv に結合する。

question-author を D1〜D5 で並列に走らせると、同じ quiz.csv への同時書き込みで
競合する。そこで各エージェントには `_parts/<domain-id>.csv` と
`_parts/<domain-id>-meta.tsv` だけを書かせ、結合はこのスクリプトが決定的に行う。

- 結合順は sections.md の front matter の domains の順（D1, D2, ... ）
- 通し番号（Q1..QN）はここで振る
- question-bank.md に追記する行もここで生成する（exam-validator が使う）

使い方:
    python tools/merge_parts.py section01-mock-exam-1
    python tools/merge_parts.py section01-mock-exam-1 --keep-parts
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# 直接実行（python .../scripts/x.py）でも兄弟モジュールを解決できるようにする。
# pytest からは scripts パッケージとして import されるため、その場合は何もしない。
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


from scripts._console import safe_stdout  # noqa: E402
from scripts.profile import domain_names, domain_quota, load_profile  # noqa: E402
from scripts.validate_quiz_csv import (  # noqa: E402
    HEADER, read_rows, validate_csv, write_rows,
)

META_FIELDS = ("local_no", "domain", "task_statement", "tested_concept", "scenario", "head")


def read_meta(path: Path) -> list[dict]:
    """meta.tsv を読む。

    ヘッダー行は「なし」が仕様だが、エージェントが付けてくることがある
    （実績: 3本目の D2）。1列目が連番でない行はヘッダーとみなして捨てる。
    """
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if not line.strip():
            continue
        cells = line.split("\t")
        if len(cells) < len(META_FIELDS):
            raise SystemExit(
                f"{path}: タブ区切りの列が {len(cells)} 個しかない"
                f"（{len(META_FIELDS)} 個必要）: {line[:80]}"
            )
        if not cells[0].strip().isdigit():
            continue                       # ヘッダー行
        rows.append(dict(zip(META_FIELDS, [c.strip() for c in cells])))
    return rows


def merge(section: Path, profile: dict, keep_parts: bool) -> dict:
    parts_dir = section / "_parts"
    if not parts_dir.is_dir():
        raise SystemExit(f"{parts_dir} がない。先に各ドメインのパートを生成する")

    names = domain_names(profile)
    # mixed モードでは本ごとに配分が違うので、セクション名で引く。
    # mock-exam モードや未登録のフォルダ名では全体ノルマに落ちる。
    quota = domain_quota(profile, section.name)

    merged: list[list[str]] = [list(HEADER)]
    bank: list[str] = []
    per_domain: dict[str, int] = {}
    global_no = 0

    for did in quota:                      # front matter の domains 順
        csv_path = parts_dir / f"{did}.csv"
        meta_path = parts_dir / f"{did}-meta.tsv"
        if not csv_path.is_file():
            raise SystemExit(f"{csv_path} がない")
        if not meta_path.is_file():
            raise SystemExit(f"{meta_path} がない")

        errors = validate_csv(csv_path)
        if errors:
            print(f"FAIL {csv_path}: {len(errors)} error(s)")
            for e in errors[:10]:
                print(f"  - {e}")
            raise SystemExit(1)

        body = read_rows(csv_path)[1:]
        meta = read_meta(meta_path)
        if len(body) != len(meta):
            raise SystemExit(
                f"{did}: CSV {len(body)} 行 と meta {len(meta)} 行が一致しない"
            )
        if len(body) != quota[did]:
            raise SystemExit(
                f"{did}: {len(body)} 問だがノルマは {quota[did]} 問"
            )

        want = names[did]
        for i, row in enumerate(body):
            if row[16].strip() != want:
                raise SystemExit(
                    f"{did} の {i + 1} 行目: Domain 列が '{row[16]}' "
                    f"（'{want}' でなければならない）"
                )

        for row, m in zip(body, meta):
            global_no += 1
            merged.append(row)
            head = (m["head"] or row[0])[:60].replace("|", "/")
            bank.append(
                f"| {section.name[:9]} | Q{global_no} | {did} | "
                f"{m['task_statement']} | {m['tested_concept'].replace('|', '/')} | "
                f"{m['scenario']} | {head} |"
            )
        per_domain[did] = len(body)

    quiz = section / "quiz.csv"
    write_rows(quiz, merged)

    errors = validate_csv(quiz)
    if errors:
        print(f"FAIL {quiz}: {len(errors)} error(s)")
        for e in errors[:10]:
            print(f"  - {e}")
        raise SystemExit(1)

    bank_out = section / "_parts" / "bank-rows.md"
    bank_out.write_text("\n".join(bank) + "\n", encoding="utf-8", newline="\n")

    if not keep_parts:
        for p in sorted(parts_dir.glob("*.csv")):
            p.unlink()
        for p in sorted(parts_dir.glob("*-meta.tsv")):
            p.unlink()

    return {"total": global_no, "per_domain": per_domain, "bank_rows": str(bank_out)}


def main(argv: list[str]) -> int:
    safe_stdout()
    ap = argparse.ArgumentParser(description="ドメイン別パートを quiz.csv に結合する")
    ap.add_argument("section", help="例: section01-mock-exam-1")
    ap.add_argument("--sections", default="sections.md")
    ap.add_argument(
        "--keep-parts", action="store_true",
        help="結合後もパートファイルを残す（既定は削除。bank-rows.md は常に残る）",
    )
    a = ap.parse_args(argv[1:])

    profile = load_profile(a.sections)
    result = merge(Path(a.section), profile, a.keep_parts)

    print(f"OK: {a.section}/quiz.csv に {result['total']} 問を結合")
    for did, n in result["per_domain"].items():
        print(f"  {did}: {n}")
    print(f"  question-bank 追記用の行: {result['bank_rows']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
