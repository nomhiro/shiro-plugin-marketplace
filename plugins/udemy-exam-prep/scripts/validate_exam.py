"""フル模試の成立条件を検証する: ドメイン配分・シラバス整合・本横断の重複。

exam-validator エージェントが呼ぶ。判定ロジックをここに置くことで、
エージェントの出力揺れに関係なく同じ基準が適用される。
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter, defaultdict
from pathlib import Path

# 直接実行（python .../scripts/x.py）でも兄弟モジュールを解決できるようにする。
# pytest からは scripts パッケージとして import されるため、その場合は何もしない。
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.profile import (
    domain_names, domain_quota, load_profile, resolve_section,
)
from scripts._console import safe_stdout
from scripts.validate_quiz_csv import read_rows

BANK_FIELDS = (
    "section", "q", "domain", "task_statement", "tested_concept", "scenario", "head",
)


def domain_counts(rows: list[list[str]]) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for row in rows[1:]:
        if len(row) == 17 and row[16].strip():
            counter[row[16].strip()] += 1
    return dict(counter)


def check_quota(
    rows: list[list[str]], profile: dict, section=None
) -> list[str]:
    """ドメイン配分と総問題数を検証する。

    section を渡すと**そのセクションの**ノルマと問題数で検証する
    （mixed モードでは本ごとに違う）。渡さない場合は全体ノルマと
    questions_per_exam で検証するので、既存の呼び出しは挙動が変わらない。
    """
    counts = domain_counts(rows)
    names = domain_names(profile)
    quota = domain_quota(profile, section)
    spec = resolve_section(profile, section) if section is not None else None
    name_to_id = {v: k for k, v in names.items()}

    errors: list[str] = []
    for name in counts:
        if name not in name_to_id:
            errors.append(
                f'unknown Domain value "{name}" - must be one of {sorted(name_to_id)}'
            )
    # このセクションのノルマに**含まれていない**ドメインの問題を明示的に落とす。
    # mixed モードの drill は担当ドメインを絞るため、担当外のドメインが混ざると
    # 「担当ドメインが N 問足りない」という間接的な報告しか出ず、原因が読めない
    # （実績: drill の1問を D1 -> D2 に変えたら D1 の不足しか報告されなかった）。
    for name, got in sorted(counts.items()):
        did = name_to_id.get(name)
        if did is not None and did not in quota:
            errors.append(
                f'{did} "{name}": {got} questions, but this section\'s quota '
                f"covers only {sorted(quota)}"
            )

    for did, want in quota.items():
        got = counts.get(names[did], 0)
        if got != want:
            errors.append(f'{did} "{names[did]}": {got} questions, expected {want}')

    total = sum(counts.values())
    want_total = spec["questions"] if spec else profile.get("questions_per_exam")
    if want_total is not None and total != want_total:
        errors.append(f"total {total} questions, expected {want_total}")
    return errors


def parse_question_bank(path) -> list[dict]:
    path = Path(path)
    if not path.is_file():
        return []
    entries: list[dict] = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) != len(BANK_FIELDS):
            continue
        if cells[0] in ("section", "---") or set(cells[0]) <= {"-", ":"}:
            continue
        entries.append(dict(zip(BANK_FIELDS, cells)))
    return entries


def check_duplicates(entries: list[dict], max_per_concept: int = 2) -> list[str]:
    grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for e in entries:
        grouped[(e["task_statement"], e["tested_concept"])].append(e)

    errors: list[str] = []
    for (ts, concept), group in sorted(grouped.items()):
        label = f'({ts}, "{concept}")'
        if len(group) > max_per_concept:
            where = ", ".join(f"{g['section']}/{g['q']}" for g in group)
            errors.append(
                f"{label} used {len(group)} times (max {max_per_concept}): {where}"
            )
        sections = [g["section"] for g in group]
        for section, n in Counter(sections).items():
            if n > 1:
                errors.append(
                    f"{label} repeated {n} times in the same section {section}"
                )
        scenarios = [g["scenario"] for g in group]
        for scenario, n in Counter(scenarios).items():
            if n > 1:
                errors.append(
                    f"{label} reused in the same scenario {scenario} {n} times "
                    "- vary the scenario when reusing a concept"
                )
    return errors


def bank_rows(entries: list[dict]) -> list[str]:
    return [
        "| " + " | ".join(e[f].replace("|", "/") for f in BANK_FIELDS) + " |"
        for e in entries
    ]


def main(argv: list[str]) -> int:
    safe_stdout()
    ap = argparse.ArgumentParser(description="フル模試の配分・整合・重複を検証する")
    ap.add_argument("--sections", required=True)
    ap.add_argument("--bank")
    ap.add_argument("csv_paths", nargs="+")
    a = ap.parse_args(argv[1:])

    profile = load_profile(a.sections)
    failed = False

    for target in a.csv_paths:
        errors = check_quota(read_rows(target), profile, section=target)
        if errors:
            failed = True
            print(f"FAIL {target}: {len(errors)} quota/syllabus error(s)")
            for e in errors:
                print(f"  - {e}")
        else:
            print(f"OK   {target}: domain quota satisfied")

    if a.bank:
        cap = profile.get("max_per_concept", 2)
        errors = check_duplicates(parse_question_bank(a.bank), max_per_concept=cap)
        if errors:
            failed = True
            print(f"FAIL {a.bank}: {len(errors)} duplication error(s)")
            for e in errors[:20]:
                print(f"  - {e}")
            if len(errors) > 20:
                print(f"  ... and {len(errors) - 20} more")
        else:
            print(f"OK   {a.bank}: no duplication violations (max {cap} per concept)")

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
