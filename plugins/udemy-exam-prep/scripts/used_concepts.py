"""question-bank.md から、指定ドメインの使用済み概念を作問プロンプト用に整形する。

3本目以降は使用済み概念が増えるため、プロンプトに手書きで貼るのは維持できない。
タスクステートメント別に「概念（使用回数・使ったシナリオ）」を並べ、
上限に達した概念を明示する。

使い方:
    python tools/used_concepts.py D1
    python tools/used_concepts.py D1 --max-per-concept 3
"""
from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

# 直接実行（python .../scripts/x.py）でも兄弟モジュールを解決できるようにする。
# pytest からは scripts パッケージとして import されるため、その場合は何もしない。
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


from scripts._console import safe_stdout  # noqa: E402
from scripts.profile import load_profile  # noqa: E402
from scripts.validate_exam import parse_question_bank  # noqa: E402


def main(argv: list[str]) -> int:
    safe_stdout()
    ap = argparse.ArgumentParser(description="使用済み概念を作問プロンプト用に整形する")
    ap.add_argument("domain", help="D1 〜 D5")
    ap.add_argument("--bank", default="question-bank.md")
    ap.add_argument("--sections", default="sections.md")
    ap.add_argument("--max-per-concept", type=int, default=None)
    a = ap.parse_args(argv[1:])

    cap = a.max_per_concept
    if cap is None:
        cap = load_profile(a.sections).get("max_per_concept", 2)

    entries = [e for e in parse_question_bank(a.bank) if e["domain"] == a.domain]
    if not entries:
        print(f"{a.domain}: まだ出題がありません（1本目の生成前）")
        return 0

    grouped: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for e in entries:
        grouped[e["task_statement"]][e["tested_concept"]].append(e["scenario"])

    def ts_key(s: str) -> list[int]:
        return [int(x) for x in s.split(".")]

    print(f"## {a.domain} の使用済み概念（全 {len(entries)} 問・上限 {cap} 回）\n")
    exhausted: list[str] = []
    for ts in sorted(grouped, key=ts_key):
        concepts = grouped[ts]
        print(f"**{ts}**（{sum(len(v) for v in concepts.values())} 問出題済み）")
        for concept, scens in sorted(concepts.items()):
            n = len(scens)
            mark = "  ← **上限到達。使用禁止**" if n >= cap else ""
            print(f"- {concept}（{n}回 / シナリオ {', '.join(sorted(set(scens)))}）{mark}")
            if n >= cap:
                exhausted.append(f"{ts}: {concept}")
        print()

    if exhausted:
        print(f"### 上限（{cap}回）に達した概念 - 絶対に使わない\n")
        for x in exhausted:
            print(f"- {x}")
        print()

    print("### 再利用する場合のルール\n")
    print(f"- 同一 `(task_statement, tested_concept)` は全6本を通じて**最大 {cap} 回**")
    print("- 同じ本の中では1回まで")
    print("- **既に使ったシナリオとは違うシナリオ**にする（上のカッコ内を確認）")
    print("- 問い方（根本原因 / 最善の第一手 / 設計選択 / アンチパターンの識別 / トレードオフ）も変える")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
