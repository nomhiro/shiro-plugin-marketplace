"""考えてみよう（Line 8）の問いの語が、選択肢のうち1つにだけ出ていないかを数える（読み取り専用）。

    python check_quiz_words.py videos/<unit> [videos/<unit> ...]

2026-10-19 新設（L3-1 の教訓: 問いの「添え」「入力」が正解にだけ出て、字面で正解が選べた。台本の再レビューは見落とし、slide-reviewer が拾った）。
SCRIPT.md の `## Line 8` の字下げ行を「ひとつ目、」「ふたつ目、」「みっつ目、」で切り、その前を問いとみなす。
語は、漢字・カタカナ・英字の2字以上のかたまりと、「漢字1字＋ひらがな1字」（添え・付け など）。
1つの選択肢にだけ出る問いの語を ★ で出す。正解かどうかは見ない（設計メモの選択肢の表と突き合わせる）。

2026-10-19 追加（L8-2 初学者役レビュー 高2: どちらも問いの語の検査では拾えなかった）:
- 本編（Line 2〜7）の語が1つの選択肢にだけ出る（機能の名前・画面の語）→ ◆ で出す
- 選択肢どうしの重なり: 1つの選択肢だけが他の2つの両方と語を共有し、他の2つどうしは何も共有しない（「ハブ」）→ ▲ で出す
- 選択肢の字数（空白を除く）。最短・最長が正解に偏っていないかを設計メモの表で見る
"""
import re
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

TOKEN = re.compile(r"[一-龥ァ-ヴーA-Za-z]{2,}|[一-龥][ぁ-ん]")
MARKS = ["ひとつ目、", "ふたつ目、", "みっつ目、"]


def qline(script: Path) -> int:
    """問いの Line 番号。見出しが「考えてみよう：問い」の行（無ければ 8）。2026-10-19 L99-1: 問いが Line 7・10 のユニットが飛ばされていた"""
    m = re.search(r"## Line (\d+) — 考えてみよう：問い", script.read_text(encoding="utf-8"))
    return int(m.group(1)) if m else 8


def line8(script: Path) -> str:
    t = script.read_text(encoding="utf-8")
    m = re.search(rf"## Line {qline(script)} —[^\n]*\n(.*?)(?=\n## )", t, re.S)
    if not m:
        return ""
    return " ".join(l.strip() for l in m.group(1).splitlines() if l.startswith("    "))


def body(script: Path) -> str:
    t = script.read_text(encoding="utf-8")
    out = []
    for n in range(2, qline(script)):
        m = re.search(rf"## Line {n} —[^\n]*\n(.*?)(?=\n## )", t, re.S)
        if m:
            out += [l.strip() for l in m.group(1).splitlines() if l.startswith("    ")]
    return " ".join(out)


def main(units):
    for u in units:
        text = line8(Path(u) / "SCRIPT.md")
        if not all(k in text for k in MARKS):
            print(f"{u}: Line 8 に「ひとつ目、」〜「みっつ目、」が無い（スキップ）")
            continue
        i1, i2, i3 = (text.index(k) for k in MARKS)
        end = text.find("少し、考えて", i3)
        q = text[:i1]
        opts = [text[i1:i2], text[i2:i3], text[i3:end if end > 0 else None]]
        qwords = sorted(set(TOKEN.findall(q)))
        hits = []
        for w in qwords:
            inside = [k + 1 for k, o in enumerate(opts) if w in o]
            if len(inside) == 1:
                hits.append(f"「{w}」→ {inside[0]} だけ")
        print(f"{u}: 問いの語が1つの選択肢にだけ出る {len(hits)} 件" + ("" if not hits else " ★ " + "／".join(hits)))
        names = [k.rstrip("、") for k in MARKS]
        sets = [set(TOKEN.findall(o.replace(k, "", 1))) for o, k in zip(opts, MARKS)]
        common = sets[0] & sets[1] & sets[2]
        sets = [s - common for s in sets]
        bwords = set(TOKEN.findall(body(Path(u) / "SCRIPT.md"))) - set(qwords)
        bhits = [f"「{w}」→ {k + 1} だけ" for w in sorted(bwords) for k in range(3)
                 if w in sets[k] and all(w not in sets[j] for j in range(3) if j != k)]
        print(f"   ◆ 本編の語が1つの選択肢にだけ出る {len(bhits)} 件" + ("" if not bhits else "：" + "／".join(bhits)))
        share = {(a, b): sets[a] & sets[b] for a in range(3) for b in range(a + 1, 3)}
        for k in range(3):
            o1, o2 = [j for j in range(3) if j != k]
            if share[tuple(sorted((k, o1)))] and share[tuple(sorted((k, o2)))] and not share[(o1, o2)]:
                print(f"   ▲ {k + 1} だけが他の2つの両方と語を共有する（{names[o1]}と{sorted(share[tuple(sorted((k, o1)))])}・"
                      f"{names[o2]}と{sorted(share[tuple(sorted((k, o2)))])}。他の2つは共有なし）")
        lens = [len(re.sub(r"[\s、。]", "", o.replace(k, "", 1))) for o, k in zip(opts, MARKS)]
        print(f"   字数（空白・句読点を除く）: {lens}")


if __name__ == "__main__":
    main(sys.argv[1:])
