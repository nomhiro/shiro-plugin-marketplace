"""講座全体（全模試）を横断して監査する。

各セクションは `finalize_section.py` で個別に検証済みだが、
「6本を1つの講座として見たときの欠陥」はそこでは見えない。

監査項目:
  1. 総問題数とセクションごとの問題数
  2. ドメイン配分（各本 / 累計）
  3. タスクステートメントのカバレッジ（全30個が全本に出ているか）
  4. シナリオの分布（各本で 8〜12 問に収まっているか）
  5. 形式比率（各本 / 累計）
  6. tested_concept の再利用回数（front matter の max_per_concept 以内か）
  7. 同一概念を複数回使うときシナリオが変わっているか
  8. 正解位置の分布（各本 / 累計）
  9. 出典の健全性（認定ページ・旧ホストの混入、出典の欠落）
 10. 問題文の重複（冒頭が酷似する問題の検出）

使い方:
    python tools/audit_course.py
    python tools/audit_course.py --check-urls
"""
from __future__ import annotations

import argparse
import difflib
import glob
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

# 直接実行（python .../scripts/x.py）でも兄弟モジュールを解決できるようにする。
# pytest からは scripts パッケージとして import されるため、その場合は何もしない。
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


from scripts._console import safe_stdout  # noqa: E402
from scripts.profile import (  # noqa: E402
    domain_names, domain_quota, forbidden_sources, load_profile,
)
from scripts.shuffle_options import position_balance  # noqa: E402
from scripts.validate_quiz_csv import (  # noqa: E402
    OPTION_PAIRS, correct_indices, read_rows,
)
from scripts.validate_exam import parse_question_bank  # noqa: E402

# 禁止ホストは sections.md front matter の forbidden_sources から読む（既定は空）
URL_RE = re.compile(r"https?://[^\s)）、。，」』】>]+")
# 問題文の冒頭がこの割合以上similarなら重複候補として報告する
SIMILARITY_THRESHOLD = 0.82
# 正解肢の文面がこの割合以上similarなら重複候補として報告する。
# 問題文より短く語彙も定型的なので、問題文よりわずかに緩い値にする。
OPTION_SIMILARITY_THRESHOLD = 0.80
# これより短い正解肢は定型句で偶然一致しやすいので比較対象にしない
OPTION_MIN_CHARS = 40


def normalize_option(text: str) -> str:
    """比較用に正解肢を正規化する。

    バッククォート・大文字小文字・空白の違いだけで別物と判定されないようにする。
    """
    t = text.lower().replace("`", "")
    return re.sub(r"\s+", " ", t).strip()


def section_paths() -> list[Path]:
    return [Path(p) for p in sorted(glob.glob("section0*/quiz.csv"))]


def audit(profile: dict, bank_path: Path, check_urls: bool) -> list[str]:
    forbidden = forbidden_sources(profile)
    problems: list[str] = []
    names = domain_names(profile)
    quota = domain_quota(profile)
    per_exam = profile["questions_per_exam"]
    want_exams = profile["mock_exams"]
    cap = profile.get("max_per_concept", 2)

    paths = section_paths()
    print(f"=== セクション: {len(paths)}/{want_exams} 本 ===")
    if len(paths) != want_exams:
        problems.append(f"セクションが {len(paths)} 本しかない（{want_exams} 本必要）")

    all_rows: list[list[str]] = []
    for p in paths:
        rows = read_rows(p)[1:]
        all_rows.extend(rows)
        counts = Counter(r[16] for r in rows)
        types = Counter(r[1] for r in rows)
        line = f"{p.parent.name}: {len(rows)}問  {dict(types)}"
        print(f"  {line}")
        if len(rows) != per_exam:
            problems.append(f"{p.parent.name}: {len(rows)}問（{per_exam}問必要）")
        for did, want in quota.items():
            got = counts.get(names[did], 0)
            if got != want:
                problems.append(
                    f"{p.parent.name}: {did} が {got}問（{want}問必要）"
                )

    print(f"\n=== 累計 ===")
    print(f"総問題数: {len(all_rows)}（目標 {per_exam * want_exams}）")
    print(f"形式: {dict(Counter(r[1] for r in all_rows))}")
    for did, want in quota.items():
        got = sum(1 for r in all_rows if r[16] == names[did])
        print(f"  {did} {names[did]}: {got}（目標 {want * want_exams}）")

    # --- question-bank による概念・シナリオ・カバレッジの監査 ---
    entries = parse_question_bank(bank_path)
    print(f"\n=== question-bank: {len(entries)} 行 ===")
    if len(entries) != len(all_rows):
        problems.append(
            f"question-bank の行数 {len(entries)} が総問題数 {len(all_rows)} と一致しない"
        )

    by_ts = Counter(e["task_statement"] for e in entries)
    print(f"タスクステートメント: {len(by_ts)} 個をカバー")
    missing = [ts for ts, n in by_ts.items() if n == 0]
    if missing:
        problems.append(f"出題のないタスクステートメント: {missing}")

    # 各本にすべてのタスクステートメントが出ているか
    per_section_ts = defaultdict(set)
    for e in entries:
        per_section_ts[e["section"]].add(e["task_statement"])
    all_ts = set(by_ts)
    for sec, ts_set in sorted(per_section_ts.items()):
        gap = all_ts - ts_set
        if gap:
            problems.append(f"{sec}: 出題のないタスクステートメント {sorted(gap)}")

    # シナリオ分布
    print("\nシナリオ分布（各本 8〜12 問が目標）:")
    for sec in sorted(per_section_ts):
        dist = Counter(e["scenario"] for e in entries if e["section"] == sec)
        out_of_band = {s: n for s, n in dist.items() if not (8 <= n <= 12)}
        flag = f"  <- 範囲外 {out_of_band}" if out_of_band else ""
        print(f"  {sec}: {dict(sorted(dist.items()))}{flag}")
        if out_of_band:
            problems.append(f"{sec}: シナリオが 8〜12 問の範囲外 {out_of_band}")

    # 概念の再利用
    grouped = defaultdict(list)
    for e in entries:
        grouped[(e["task_statement"], e["tested_concept"])].append(e)
    reuse = Counter(len(v) for v in grouped.values())
    print(f"\n概念の再利用回数（上限 {cap}）: {dict(sorted(reuse.items()))}")
    for key, group in sorted(grouped.items()):
        if len(group) > cap:
            where = ", ".join(f"{g['section']}/{g['q']}" for g in group)
            problems.append(f"概念 {key} を {len(group)} 回使用（上限 {cap}）: {where}")
        scen = Counter(g["scenario"] for g in group)
        for s, n in scen.items():
            if n > 1:
                problems.append(
                    f"概念 {key} を同じシナリオ {s} で {n} 回使用（シナリオを変える）"
                )

    # --- 正解位置の分布 ---
    print("\n=== 正解位置の分布 ===")
    for p in paths:
        rows = read_rows(p)
        warn = []
        for qt in ("multiple-choice", "multi-select"):
            for e in position_balance(rows, qt):
                if not e["within_tolerance"]:
                    warn.append(f"{qt} pos{e['position']} {e['actual']}/{e['expected']}")
        print(f"  {p.parent.name}: {'OK' if not warn else ' / '.join(warn)}")
        if warn:
            problems.append(f"{p.parent.name}: 正解位置が許容外 {warn}")

    # --- 出典 ---
    print("\n=== 出典 ===")
    hosts: Counter[str] = Counter()
    urls: set[str] = set()
    no_source = 0
    for p in paths:
        for i, r in enumerate(read_rows(p)[1:], 1):
            found = URL_RE.findall(r[15])
            if not found and "公式 Exam Guide" not in r[15]:
                no_source += 1
                problems.append(f"{p.parent.name}/Q{i}: 出典がない")
            for u in found:
                u = u.rstrip(".,")
                host = re.match(r"https?://([^/]+)", u).group(1)
                hosts[host] += 1
                urls.add(u)
                if any(host == b or host.endswith("." + b) for b in forbidden):
                    problems.append(f"{p.parent.name}/Q{i}: 不適切な出典ホスト {host}")
    print(f"ホスト別: {dict(hosts)}")
    print(f"ユニーク URL: {len(urls)} 件 / 出典なし: {no_source} 問")

    if check_urls:
        import time
        import urllib.error
        import urllib.request
        print("\nURL 到達確認中...")
        for u in sorted(urls):
            try:
                req = urllib.request.Request(
                    u, headers={"User-Agent": "Mozilla/5.0 (cca-f-audit/1.0)"}
                )
                with urllib.request.urlopen(req, timeout=20) as resp:
                    code = resp.status
            except urllib.error.HTTPError as e:
                code = e.code
            except Exception:
                code = 0
            if code != 200:
                problems.append(f"URL が 200 を返さない [{code}]: {u}")
            time.sleep(1.5)
        print(f"確認完了: {len(urls)} 件")

    # --- 問題文の重複 ---
    print("\n=== 問題文の重複検査 ===")
    heads = []
    for p in paths:
        for i, r in enumerate(read_rows(p)[1:], 1):
            heads.append((f"{p.parent.name}/Q{i}", r[0]))
    dupes = 0
    for i in range(len(heads)):
        for j in range(i + 1, len(heads)):
            ratio = difflib.SequenceMatcher(
                None, heads[i][1][:200], heads[j][1][:200]
            ).ratio()
            if ratio >= SIMILARITY_THRESHOLD:
                dupes += 1
                problems.append(
                    f"問題文が酷似（{ratio:.0%}）: {heads[i][0]} と {heads[j][0]}"
                )
    print(f"類似度 {SIMILARITY_THRESHOLD:.0%} 以上の組: {dupes} 件")

    # --- 正解肢の重複 ---
    # 問題文が別でも「正解として提示する事実」が使い回されていると、
    # 先の模試を解いた受講者が内容を読まずに正解を選べてしまう。
    # 主概念（tested_concept）が別でも、正解肢の文面が酷似していれば報告する。
    print("\n=== 正解肢の重複検査 ===")
    opts: list[tuple[str, str, str]] = []   # (問題ラベル, 選択肢ラベル, 正規化文面)
    for p in paths:
        for i, r in enumerate(read_rows(p)[1:], 1):
            for n in correct_indices(r[14]):
                if not n.isdigit():
                    continue
                col = OPTION_PAIRS[int(n) - 1][0]
                text = normalize_option(r[col])
                if len(text) >= OPTION_MIN_CHARS:
                    opts.append((f"{p.parent.name}/Q{i}", f"opt{n}", text))

    opt_dupes = 0
    for i in range(len(opts)):
        for j in range(i + 1, len(opts)):
            if opts[i][0] == opts[j][0]:
                continue                    # 同一問題内は比較しない
            ratio = difflib.SequenceMatcher(None, opts[i][2], opts[j][2]).ratio()
            if ratio >= OPTION_SIMILARITY_THRESHOLD:
                opt_dupes += 1
                problems.append(
                    f"正解肢が酷似（{ratio:.0%}）: "
                    f"{opts[i][0]}/{opts[i][1]} と {opts[j][0]}/{opts[j][1]}"
                )
    print(f"正解肢 {len(opts)} 件 / 類似度 {OPTION_SIMILARITY_THRESHOLD:.0%} 以上の組: {opt_dupes} 件")

    return problems


def main(argv: list[str]) -> int:
    safe_stdout()
    ap = argparse.ArgumentParser(description="講座全体を横断監査する")
    ap.add_argument("--sections", default="sections.md")
    ap.add_argument("--bank", default="question-bank.md")
    ap.add_argument("--check-urls", action="store_true")
    a = ap.parse_args(argv[1:])

    profile = load_profile(a.sections)
    problems = audit(profile, Path(a.bank), a.check_urls)

    print("\n" + "=" * 60)
    if problems:
        print(f"FAIL: {len(problems)} 件の問題")
        for p in problems[:40]:
            print(f"  - {p}")
        if len(problems) > 40:
            print(f"  ... 他 {len(problems) - 40} 件")
        return 1
    print("OK: 講座全体の監査をすべて通過しました")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
