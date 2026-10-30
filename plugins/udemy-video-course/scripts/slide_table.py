"""ユニット doc の §5（図解の要求）を、作った slides の実物から書き出す（2026-10-09）。

    python slide_table.py videos/<unit>                 # 表を標準出力へ
    python slide_table.py videos/<unit> --write <doc>   # doc の「## 5.」節を置き換える

§5 を手で書くと、slides.py を直すたびに食い違う（2026-10-08 に 3-1-1〜3-1-3 で全部陳腐化した）。
**正本は slides.py**。この表は「語りのどの語で何が現れるか」を人が確かめるための写し。

読むもの:
- STORYBOARD.md … フレームの順・タイトル（＝ページ。同じタイトルが続く枚が1ページ）・語り・切り替え
- compositions/frames/*.html … `tl.fromTo(..., { opacity: 0 }, ...)` の行末コメント（slides.py の reveal の注記と着地秒）
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass


def frames(unit: Path):
    sb = (unit / "STORYBOARD.md").read_text(encoding="utf-8")
    out = []
    for m in re.finditer(r"^## Frame (\d+) — (.*?)\n(.*?)(?=^## Frame |\Z)", sb, re.S | re.M):
        body = m.group(3)
        g = lambda k: (re.search(rf"^- {k}: (.*)$", body, re.M) or [None, ""])[1].strip()
        src = g("src")
        notes = []
        html = unit / src
        if src and html.is_file():
            for n in re.finditer(r'tl\.fromTo\("#[^"]+", \{ opacity: 0 \}.*?// (.*?)（着地 [\d.]+s）', html.read_text(encoding="utf-8")):
                notes.append(n.group(1).strip())
        out.append({"n": int(m.group(1)), "title": m.group(2).strip(), "vo": g("voiceover").strip('"'),
                    "tr": g("transition_in"), "notes": notes})
    return out


def table(unit: Path) -> str:
    fr = frames(unit)
    pages, cur = [], None
    for f in fr:
        if cur is None or f["title"] != cur["title"]:
            cur = {"title": f["title"], "frames": []}
            pages.append(cur)
        cur["frames"].append(f)
    lines = [f"語り **{len(fr)}行**（1行＝1フレーム＝音声 wav 1本）を **{len(pages)}ページ**にまとめる（`slide-format.md` §2c）。",
             "ページの中では前の行の図が残り、その行の図だけが語末で足される。切り替えはページの頭だけ crossfade、ページの中は cut。",
             "",
             f"**正本は `videos/{unit.name}/slides.py`**。この表は `python slide_table.py videos/{unit.name} --write <この doc>` で作り直す（手で直さない）。",
             ""]
    for k, p in enumerate(pages, 1):
        a, b = p["frames"][0]["n"], p["frames"][-1]["n"]
        lines.append(f"### ページ{k}　{p['title']}（F{a}" + (f"〜F{b}）" if b != a else "）"))
        lines.append("")
        lines.append("| F | 語り | 語末で足すもの |")
        lines.append("|---|---|---|")
        for f in p["frames"]:
            notes = "<br>".join(f["notes"]) if f["notes"] else "（足すものなし）"
            lines.append(f"| {f['n']} | {f['vo']} | {notes} |")
        lines.append("")
    return "\n".join(lines)


def main(argv):
    ap = argparse.ArgumentParser(description="ユニット doc の §5 を slides の実物から書き出す")
    ap.add_argument("unit")
    ap.add_argument("--write", default=None, help="置き換える doc（「## 5.」節）")
    a = ap.parse_args(argv[1:])
    t = table(Path(a.unit))
    if not a.write:
        print(t)
        return 0
    doc = Path(a.write)
    raw = doc.read_bytes()
    crlf = b"\r\n" in raw
    s = raw.decode("utf-8").replace("\r\n", "\n")
    m = re.search(r"^## 5\..*?$\n(.*?)(?=^## (?!5\.))", s, re.S | re.M)
    if not m:
        print(f"FAIL: {doc} に「## 5.」節が無い")
        return 1
    s = s[: m.start(1)] + "\n" + t + "\n" + s[m.end(1):]
    doc.write_bytes((s.replace("\n", "\r\n") if crlf else s).encode("utf-8"))
    print(f"OK: {doc} の §5 を書き換えた")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
