"""レクチャーの台本（読み上げる行だけ）と小テストを、ユーザーが通しで読める1本の Markdown にまとめる（新設 2026-10-18）。

    python lecture_script_view.py <出力.md> <タイトル> <unit-slug>... [--quiz <quiz.md>]
    例: python lecture_script_view.py lectures/01_xxx/L1-1_台本確認.md "L1-1 <レクチャー名>" \\
            lecture-1-1-open <unit> <unit> lecture-1-1-close --quiz lectures/01_xxx/L1-1_quiz.md

- 読み上げの正本は各 `videos/<slug>/SCRIPT.md`（字下げ行）。ここは読むための写しで、**直すときは SCRIPT.md を直して作り直す**。
- 見出しは `## Line N — 名前 (Frame N)` の「名前」。無音のフレームは「（無音 6秒）」と書く。字数は句読点込み。
"""
import re
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

sys.path.insert(0, str(Path(__file__).resolve().parent))
import course_config  # noqa: E402

COURSE = course_config.load()
ROOT = COURSE.root
from tts import spoken_by_frame  # noqa: E402

HEAD = re.compile(r"^##\s+(?:Line\s+\d+\s+—\s+(.+?)\s+\(Frame\s+(\d+)\)|Frame\s+(\d+)\s+—\s+(.+))$")


def unit_section(slug: str) -> tuple[str, int]:
    script = COURSE.unit(slug) / "SCRIPT.md"
    spoken = spoken_by_frame(script)
    title = script.read_text(encoding="utf-8").splitlines()[0].removeprefix("# SCRIPT — ")
    out = [f"## {title}", ""]
    for line in script.read_text(encoding="utf-8").splitlines():
        m = HEAD.match(line)
        if not m:
            continue
        if m.group(2):
            f = int(m.group(2))
            out += [f"**F{f}　{m.group(1)}**", "", spoken.get(f, "（台詞なし）"), ""]
        else:
            out += [f"**F{m.group(3)}　{m.group(4)}**", "", "（無音 6秒）", ""]
    total = sum(len(v) for v in spoken.values())
    out.insert(1, f"\n`{slug}/SCRIPT.md`・{len(spoken)}行・{total}字\n")
    return "\n".join(out), total


def main(argv: list[str]) -> int:
    quiz = None
    if "--quiz" in argv:
        i = argv.index("--quiz")
        quiz = ROOT / argv[i + 1]
        argv = argv[:i] + argv[i + 2:]
    out, title, slugs = ROOT / argv[1], argv[2], argv[3:]
    parts, totals = [], []
    for s in slugs:
        text, n = unit_section(s)
        parts.append(text)
        totals.append((s, n))
    head = [f"# {title} — 台本の確認用（読み上げる行だけ）", "",
            "> `lecture_script_view.py` が SCRIPT.md から作った写し。**直すときは各 SCRIPT.md を直して作り直す。**", "",
            "| 動画 | 字数 |", "|---|---|"] + [f"| {s} | {n} |" for s, n in totals] + [""]
    body = "\n\n---\n\n".join(parts)
    if quiz:
        q = quiz.read_text(encoding="utf-8")
        body += "\n\n---\n\n# 小テスト\n\n" + q[q.index("## 問題"):] if "## 問題" in q else q
    out.write_text("\n".join(head) + "\n" + body + "\n", encoding="utf-8", newline="\n")
    print(f"OK: {out}（{len(slugs)}本・計{sum(n for _, n in totals)}字）")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
