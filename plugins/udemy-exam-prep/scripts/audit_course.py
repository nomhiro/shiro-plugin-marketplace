"""講座全体（全模試）を横断して監査する。

各セクションは `finalize_section.py` で個別に検証済みだが、
「6本を1つの講座として見たときの欠陥」はそこでは見えない。

監査項目:
  1. 総問題数とセクションごとの問題数
  2. ドメイン配分（各本 / 累計）
  3. タスクステートメントのカバレッジ（合計が本数以上のスキルが全本に出ているか）
  4. 問い方の型 / シナリオの分布（front matter の方針に従う）
  5. 形式比率（各本 / 累計）
  6. tested_concept の再利用回数（front matter の max_per_concept 以内か）
  7. 同一概念を複数回使うときシナリオが変わっているか
  8. 正解位置の分布（各本 / 累計）
  9. 出典の健全性（認定ページ・旧ホストの混入、出典の欠落）
 10. 問題文の重複（冒頭が酷似する問題の検出）
 11. 正解肢の重複（正解として提示する事実の使い回し）
 12. tested_concept ラベルの近似重複
 13. 創作識別子（ツール名・フィールド名）の衝突

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
#
# **実測に基づいて 0.80 から下げている。** ある講座の6本目で見つかった重複は、
# 問い方（root-cause の診断 / 記述選択 / 対処の選択）が違うだけで文面が散り、
# 実測 2〜50% に分布していた。0.80 では1件も捕まらなかった。
#   - 同じ継続技法（部分出力を含めて続きを生成させる）: **48%**
#   - 同じ API フラグ（fork_session でセッション分岐）: **50%**
# いずれも 0.55 でも取り逃がすため 0.45 とする。
# 明白な使い回しは FAIL、判断が要る候補は WARN に分ける。
# 低い閾値の検出をそのまま FAIL にすると、レビューで許容した隣接まで赤くなり
# 「監査を無視する習慣」を作ってしまう（本スクリプトが実際にその状態だった）。
OPTION_SIMILARITY_FAIL = 0.80
OPTION_SIMILARITY_THRESHOLD = 0.45
# これより短い正解肢は定型句で偶然一致しやすいので比較対象にしない
OPTION_MIN_CHARS = 40
# tested_concept のラベルがこの割合以上similarなら重複候補として報告する。
# 実測でこの検査が最も多く捕まえた（55〜85%）。文面の照合をすり抜けた重複も
# ラベルには残る（ラベルは作問者が「何を問うたか」を書くため）。
CONCEPT_SIMILARITY_THRESHOLD = 0.55

# 創作識別子（ツール名・フィールド名など）の判定用。
# digest に出現しない snake_case を「作問者が創作した名前」とみなす。
IDENT_RE = re.compile(r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b")
DIGEST_GLOB = "research/*.md"
# **ガードレール文書は digest コーパスから除外する。**
# この文書は過去の事故で使われた創作名を本文に引用するため、含めると
# その創作名が「公式名」と誤判定されてブロックリストから消える（実測3件）。
DIGEST_EXCLUDE = ("AUTHORING-GUARDRAILS",)


def normalize_option(text: str) -> str:
    """比較用に正解肢を正規化する。

    バッククォート・大文字小文字・空白の違いだけで別物と判定されないようにする。
    """
    t = text.lower().replace("`", "")
    return re.sub(r"\s+", " ", t).strip()


def digest_corpus() -> str:
    """公式名の判定に使う digest 本文。ガードレール文書は除く。"""
    parts = []
    for f in sorted(glob.glob(DIGEST_GLOB)):
        if any(x in Path(f).name for x in DIGEST_EXCLUDE):
            continue
        parts.append(Path(f).read_text(encoding="utf-8", errors="replace"))
    return " ".join(parts)


def invented_identifiers(paths: list[Path], corpus: str) -> dict[str, set[str]]:
    """創作識別子 -> それが出現する問題ラベルの集合。

    受講者が実際に目にする面（Question と Answer Option）だけを見る。
    解説は訳を含むため、同じ語が両言語で重複して拾われる。
    """
    owner: dict[str, set[str]] = defaultdict(set)
    for p in paths:
        for i, r in enumerate(read_rows(p)[1:], 1):
            if len(r) != 17:
                continue
            blob = r[0] + " " + " ".join(r[opt] for opt, _ in OPTION_PAIRS)
            for name in set(IDENT_RE.findall(blob)):
                if name in corpus:
                    continue
                owner[name].add(f"{p.parent.name}/Q{i}")
    return owner


def scenario_policy(profile: dict) -> dict:
    """シナリオ検査の方針を front matter から決める。

    固定シナリオバンク（`scenarios:`）を持つ資格は、各本に各シナリオが
    均等に出ることが要件になる。持たない資格は `scenario` 列を
    **問い方の型**に転用しているため型ごとの均等配分は要件ではなく、
    `scenario_ratio_min`（非シナリオ型を除いた割合の下限）だけを検査する。
    """
    ratio_raw = str(profile.get("scenario_ratio_min") or "").strip().rstrip("%")
    try:
        ratio_min = float(ratio_raw) / 100 if ratio_raw else None
    except ValueError:
        ratio_min = None
    non_scenario = {
        str(x).strip()
        for x in (profile.get("non_scenario_codes") or ["knowledge"])
    }
    has_bank = bool(profile.get("scenarios"))
    return {
        "mode": "bank" if has_bank else "ratio",
        "ratio_min": ratio_min,
        "non_scenario": non_scenario,
    }


def section_paths() -> list[Path]:
    return [Path(p) for p in sorted(glob.glob("section0*/quiz.csv"))]


def audit(profile: dict, bank_path: Path, check_urls: bool) -> tuple[list[str], list[str]]:
    forbidden = forbidden_sources(profile)
    problems: list[str] = []
    warnings: list[str] = []
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
    # **「全スキルが全本に1問以上」を要件にしてはいけない。** 公式ウェイトが
    # 小さいスキルは全本の合計が本数未満になるため、数学的に全本へ置けない。
    # 実績: ある資格の 7.3 はウェイト 1.0% で6本合計3問 -> 最大 3/6 本にしか出せず、
    # それを FAIL にすると監査が常に赤くなり「監査を無視する習慣」を作ってしまう。
    # そこで合計が本数以上あるスキルだけ、全本に出ていることを要件にする。
    n_sections = len(per_section_ts)
    for sec, ts_set in sorted(per_section_ts.items()):
        gap = sorted(
            ts for ts, total in by_ts.items()
            if total >= n_sections and ts not in ts_set
        )
        if gap:
            problems.append(f"{sec}: 出題のないタスクステートメント {gap}")
    thin = {ts: n for ts, n in sorted(by_ts.items()) if n < n_sections}
    if thin:
        print(f"  全本に置けないスキル（合計 < 本数 {n_sections}・要件外）: {thin}")

    # シナリオ分布。
    #
    # 固定シナリオバンクを持つ資格だけ均等配分を要件にする。持たない資格は
    # `scenario` 列を**問い方の型**に転用しているため型ごとの均等配分は要件ではなく、
    # front matter の `scenario_ratio_min`（非シナリオ型を除いた割合の下限）を見る。
    # 実績: 8-12 問という固定の帯を全資格に当てると、型に転用している資格では
    # 6本すべてが FAIL になる（実測 tradeoff 4問 / design 17問 など）。
    policy = scenario_policy(profile)
    if policy["mode"] == "bank":
        print("")
        print("シナリオ分布（各本 8-12 問が目標）:")
        for sec in sorted(per_section_ts):
            dist = Counter(e["scenario"] for e in entries if e["section"] == sec)
            out_of_band = {s: n for s, n in dist.items() if not (8 <= n <= 12)}
            flag = f"  <- 範囲外 {out_of_band}" if out_of_band else ""
            print(f"  {sec}: {dict(sorted(dist.items()))}{flag}")
            if out_of_band:
                problems.append(f"{sec}: シナリオが 8-12 問の範囲外 {out_of_band}")
    else:
        rmin = policy["ratio_min"]
        label = (
            f"（シナリオ率の下限 {rmin:.0%}）" if rmin is not None
            else "（下限の指定なし）"
        )
        print("")
        print(f"問い方の型の分布{label}:")
        for sec in sorted(per_section_ts):
            dist = Counter(e["scenario"] for e in entries if e["section"] == sec)
            total = sum(dist.values())
            non = sum(n for s, n in dist.items() if s in policy["non_scenario"])
            ratio = (total - non) / total if total else 0.0
            ng = rmin is not None and ratio < rmin
            flag = f"  <- シナリオ率 {ratio:.1%} が下限を下回る" if ng else ""
            print(
                f"  {sec}: {dict(sorted(dist.items()))}"
                f" / シナリオ率 {ratio:.1%}{flag}"
            )
            if ng:
                problems.append(
                    f"{sec}: シナリオ率 {ratio:.1%} が下限 {rmin:.0%} を下回る"
                    f"（非シナリオ型 {sorted(policy['non_scenario'])} が {non}/{total} 問）"
                )

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
                msg = (
                    f"正解肢が酷似（{ratio:.0%}）: "
                    f"{opts[i][0]}/{opts[i][1]} と {opts[j][0]}/{opts[j][1]}"
                )
                (problems if ratio >= OPTION_SIMILARITY_FAIL else warnings).append(msg)
    print(f"正解肢 {len(opts)} 件 / 類似度 {OPTION_SIMILARITY_THRESHOLD:.0%} 以上の組: {opt_dupes} 件")

    # --- tested_concept ラベルの近似重複 ---
    #
    # 文面の照合をすり抜けた重複もラベルには残る（ラベルは作問者が
    # 「何を問うたか」を書くため）。実測でこの検査が最も多く捕まえた。
    print("")
    print("=== tested_concept の近似重複 ===")
    labels = [(f"{e['section']}/{e['q']}", e["task_statement"], e["tested_concept"])
              for e in entries]
    label_dupes = 0
    for i in range(len(labels)):
        for j in range(i + 1, len(labels)):
            ratio = difflib.SequenceMatcher(None, labels[i][2], labels[j][2]).ratio()
            if ratio >= CONCEPT_SIMILARITY_THRESHOLD:
                label_dupes += 1
                warnings.append(
                    f"tested_concept が近い（{ratio:.0%}）: "
                    f"{labels[i][0]} {labels[i][1]} {labels[i][2]} / "
                    f"{labels[j][0]} {labels[j][1]} {labels[j][2]}"
                )
    print(f"閾値 {CONCEPT_SIMILARITY_THRESHOLD:.0%} 以上の組: {label_dupes} 件")

    # --- 創作識別子の衝突 ---
    #
    # ツール名・フィールド名のような固有名は、角度を変えても**同じ名前が出た瞬間に
    # 受講者は前の本を思い出す**。類似度では捕まらない（実績: 正解肢8% /
    # 問題文20% / ラベル60% と全指標が閾値未満でも差し替えが必要だった）。
    # 同一本の中での共有も検出する（受講者が2問を結び付けて見てしまう）。
    print("")
    print("=== 創作識別子の衝突 ===")
    corpus = digest_corpus()
    if not corpus:
        print(f"SKIP: {DIGEST_GLOB} に digest が無いため判定できません")
    else:
        owner = invented_identifiers(paths, corpus)
        collisions = {k: v for k, v in sorted(owner.items()) if len(v) > 1}
        for name, where in collisions.items():
            problems.append(
                f"創作識別子 {name} を {len(where)} 問で使用: {', '.join(sorted(where))}"
            )
        print(f"創作識別子 {len(owner)} 件 / 衝突 {len(collisions)} 件")

    return problems, warnings


def main(argv: list[str]) -> int:
    safe_stdout()
    ap = argparse.ArgumentParser(description="講座全体を横断監査する")
    ap.add_argument("--sections", default="sections.md")
    ap.add_argument("--bank", default="question-bank.md")
    ap.add_argument("--check-urls", action="store_true")
    ap.add_argument(
        "--strict", action="store_true",
        help="WARN（人の判断が要る重複候補）も失敗として扱う",
    )
    a = ap.parse_args(argv[1:])

    profile = load_profile(a.sections)
    problems, warnings = audit(profile, Path(a.bank), a.check_urls)
    if a.strict:
        problems, warnings = problems + warnings, []

    print("")
    print("=" * 60)
    if warnings:
        print(
            f"WARN: {len(warnings)} 件の重複候補"
            "（レビューして許容か差し替えかを判断する）"
        )
        for w in warnings[:40]:
            print(f"  - {w}")
        if len(warnings) > 40:
            print(f"  ... 他 {len(warnings) - 40} 件")
        print("")
    if problems:
        print(f"FAIL: {len(problems)} 件の問題")
        for pr in problems[:40]:
            print(f"  - {pr}")
        if len(problems) > 40:
            print(f"  ... 他 {len(problems) - 40} 件")
        return 1
    tail = "（WARN は残っています）" if warnings else ""
    print("OK: 講座全体の監査をすべて通過しました" + tail)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
