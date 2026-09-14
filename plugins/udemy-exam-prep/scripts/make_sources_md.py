"""セクションの sources.md を quiz.csv と bank-rows.md から生成する。

出典一覧（URL に通し番号を振る）と、問題ごとの対応表を作る。
Exam Guide にしか根拠がない論点は URL を持たないので、その旨を列で示す。

使い方:
    python "${CLAUDE_PLUGIN_ROOT}/scripts/make_sources_md.py" section02-mock-exam-2

ホスト名の表示名（`source_titles`）と Exam Guide 出典の表記（`guide_citation`）、
出典に使わないホスト（`forbidden_sources`）は sections.md front matter から読む。
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import OrderedDict
from datetime import date
from pathlib import Path

# 直接実行（python .../scripts/x.py）でも兄弟モジュールを解決できるようにする。
# pytest からは scripts パッケージとして import されるため、その場合は何もしない。
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


from scripts._console import safe_stdout  # noqa: E402
from scripts.profile import (  # noqa: E402
    ProfileError, forbidden_sources, guide_citation, load_profile, source_titles,
)
from scripts.validate_quiz_csv import read_rows  # noqa: E402

URL_RE = re.compile(r"https?://[^\s)）、。，」』】>]+")

# ホスト名 → 表示名は sections.md front matter の source_titles から読む（既定は空）


def build_note(profile: dict) -> str:
    """Exam Guide 出典の扱いについての注記。資格ごとの表記は front matter から取る。"""
    cite = guide_citation(profile)
    lines = [
        "",
        f"> Exam Guide にしか根拠がない論点は、URL ではなく `{cite} §<節> Task Statement X.Y`",
        "> の形で各問の解説に記載している。",
    ]
    bad = forbidden_sources(profile)
    if bad:
        lines.append("> 次のホストは出典に使わない: " + " / ".join(f"`{h}`" for h in bad))
    lines.append("")
    return chr(10).join(lines)


def build(section: Path, date: str, profile: dict | None = None) -> str:
    profile = profile or {}
    titles = source_titles(profile)
    cite = guide_citation(profile)
    rows = read_rows(section / "quiz.csv")[1:]
    bank = [
        [c.strip() for c in line.strip("| ").split(" | ")]
        for line in (section / "_parts" / "bank-rows.md").read_text(encoding="utf-8").splitlines()
        if line.startswith("|")
    ]
    if len(rows) != len(bank):
        raise SystemExit(
            f"{section.name}: quiz.csv {len(rows)} 行と bank-rows.md {len(bank)} 行が一致しない"
        )

    urls: OrderedDict[str, int] = OrderedDict()
    per_q: list[tuple[list[int], bool]] = []
    for r in rows:
        ids = []
        for u in URL_RE.findall(r[15]):
            u = u.rstrip(".,")
            if u not in urls:
                urls[u] = len(urls) + 1
            ids.append(urls[u])
        per_q.append((ids, "Exam Guide" in r[15]))

    lines = [
        f"# {section.name} 出典",
        "",
        f"最終更新: {date}",
        "",
        "## 参照ドキュメント",
        "",
        "| # | タイトル | URL | 取得日 |",
        "|---|---------|-----|--------|",
    ]
    for u, i in urls.items():
        host = re.match(r"https?://([^/]+)", u).group(1)
        tail = u.rstrip("/").rsplit("/", 1)[-1].replace("-", " ")
        lines.append(f"| {i} | {titles.get(host, host)}: {tail} | {u} | {date} |")
    lines += [build_note(profile).strip(), "", "## 問題と出典の対応", "",
              "| 問題# | domain | task_statement | tested_concept | シナリオ | 出典# | Exam Guide 参照 |",
              "|-------|--------|----------------|----------------|---------|-------|----------------|"]
    for (ids, guide), b in zip(per_q, bank):
        _sec, q, dom, ts, concept, scen, _head = b
        src = ", ".join(str(i) for i in ids) if ids else "-"
        lines.append(f"| {q} | {dom} | {ts} | {concept} | {scen} | {src} | {'あり' if guide else ''} |")

    return "\n".join(lines) + "\n"


def main(argv: list[str]) -> int:
    safe_stdout()
    ap = argparse.ArgumentParser(description="セクションの sources.md を生成する")
    ap.add_argument("section")
    ap.add_argument("--sections", default="sections.md")
    ap.add_argument("--date", default=date.today().isoformat())
    a = ap.parse_args(argv[1:])

    try:
        profile = load_profile(a.sections)
    except (ProfileError, FileNotFoundError, OSError):
        profile = {}

    section = Path(a.section)
    text = build(section, a.date, profile)
    out = section / "sources.md"
    out.write_text(text, encoding="utf-8", newline="\n")

    n_urls = text.count("| http")
    n_rows = len([l for l in text.splitlines() if l.startswith("| Q")])
    print(f"OK: {out} を生成（参照ドキュメント {n_urls} 件 / 問題対応 {n_rows} 行）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
