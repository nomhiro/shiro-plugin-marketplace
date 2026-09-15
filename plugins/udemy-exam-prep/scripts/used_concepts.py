"""question-bank.md から、指定ドメインの使用済み概念を作問プロンプト用に整形する。

3本目以降は使用済み概念が増えるため、プロンプトに手書きで貼るのは維持できない。
タスクステートメント別に「概念（使用回数・使ったシナリオ）」を並べ、
上限に達した概念を明示する。

**作問エージェントには `--all` の出力を渡す。** ドメインごとに切り出したものだけを
渡すと、他ドメインが所有する概念が構造的に見えず重複が通ってしまう。
実績: ある講座の6本目で見つかった重複6件は**すべて他ドメインの履歴にある重複**で、
担当エージェントからは1件も見えなかった。

使い方:
    python tools/used_concepts.py D1
    python tools/used_concepts.py --all --out .work/used-all.md
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


def render(entries: list[dict], label: str, cap: int, emit) -> None:
    """1ドメイン分の使用済み概念を emit に流す。"""
    grouped: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for e in entries:
        grouped[e["task_statement"]][e["tested_concept"]].append(e["scenario"])

    def ts_key(s: str) -> list[int]:
        try:
            return [int(x) for x in s.split(".")]
        except ValueError:
            return [9999]

    emit(f"## {label} の使用済み概念（全 {len(entries)} 問・上限 {cap} 回）")
    emit("")
    exhausted: list[str] = []
    for ts in sorted(grouped, key=ts_key):
        concepts = grouped[ts]
        emit(f"**{ts}**（{sum(len(v) for v in concepts.values())} 問出題済み）")
        for concept, scens in sorted(concepts.items()):
            n = len(scens)
            mark = "  <- **上限到達。使用禁止**" if n >= cap else ""
            emit(f"- {concept}（{n}回 / シナリオ {', '.join(sorted(set(scens)))}）{mark}")
            if n >= cap:
                exhausted.append(f"{ts}: {concept}")
        emit("")

    if exhausted:
        emit(f"### 上限（{cap}回）に達した概念 - 絶対に使わない")
        emit("")
        for x in exhausted:
            emit(f"- {x}")
        emit("")


def finish(lines: list[str], cap: int, out: str | None) -> None:
    """末尾の共通ルールを足して、標準出力かファイルへ書き出す。

    **ファイル出力はこの関数が UTF-8 で行う。** シェルのリダイレクトに頼ると
    Windows では既定コードページ（cp932）で保存され、読み手が壊れた内容を
    受け取る（実績: 8ファイルすべてが cp932 になり作問エージェントが読めなかった）。
    """
    lines.append("### 再利用する場合のルール")
    lines.append("")
    lines.append(
        f"- 同一 `(task_statement, tested_concept)` は全本を通じて**最大 {cap} 回**"
    )
    lines.append("- 同じ本の中では1回まで")
    lines.append("- **既に使ったシナリオとは違うシナリオ**にする（上のカッコ内を確認）")
    lines.append(
        "- 問い方（根本原因 / 最善の第一手 / 設計選択 / "
        "アンチパターンの識別 / トレードオフ）も変える"
    )
    text = (chr(10)).join(lines) + chr(10)
    if out:
        path = Path(out)
        if path.parent != Path(""):
            path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline=chr(10))
        print(f"{path} に書き出しました（UTF-8 / {len(lines)} 行）")
    else:
        print(text, end="")


def main(argv: list[str]) -> int:
    safe_stdout()
    ap = argparse.ArgumentParser(description="使用済み概念を作問プロンプト用に整形する")
    ap.add_argument("domain", nargs="?", help="D1 〜 D8。--all を使うなら省略する")
    ap.add_argument(
        "--all", action="store_true",
        help="全ドメインをまとめて出す（作問エージェントにはこれを渡す）",
    )
    ap.add_argument("--out", help="出力先ファイル。スクリプト自身が UTF-8 で書く")
    ap.add_argument("--bank", default="question-bank.md")
    ap.add_argument("--sections", default="sections.md")
    ap.add_argument("--max-per-concept", type=int, default=None)
    a = ap.parse_args(argv[1:])

    if not a.all and not a.domain:
        ap.error("ドメインを指定するか --all を付けてください")

    cap = a.max_per_concept
    if cap is None:
        cap = load_profile(a.sections).get("max_per_concept", 2)

    lines: list[str] = []
    emit = lines.append
    all_entries = parse_question_bank(a.bank)

    if a.all:
        if not all_entries:
            emit("まだ出題がありません（1本目の生成前）")
        else:
            by_domain: dict[str, list[dict]] = defaultdict(list)
            for e in all_entries:
                by_domain[e["domain"]].append(e)
            emit("# 全ドメインの使用済み概念")
            emit("")
            emit("> 他ドメインが所有する論点にも触れないよう、全ドメイン分を載せている。")
            emit("")
            for dom in sorted(by_domain):
                render(by_domain[dom], dom, cap, emit)
        finish(lines, cap, a.out)
        return 0

    entries = [e for e in all_entries if e["domain"] == a.domain]
    if not entries:
        msg = f"{a.domain}: まだ出題がありません（1本目の生成前）"
        if a.out:
            Path(a.out).write_text(msg + chr(10), encoding="utf-8", newline=chr(10))
        print(msg)
        return 0

    render(entries, a.domain, cap, emit)
    finish(lines, cap, a.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
