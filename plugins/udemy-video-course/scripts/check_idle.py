"""「読んでいるのに画面が増えない時間」を検出する（2026-10-09。slide-reviewer が全ユニットで繰り返し指摘した型）。

    python check_idle.py videos/<unit-slug> [--first 4.0] [--gap 7.0]

各フレームの HTML（slides.py の生成物）から、フェードと矢印の描画の開始時刻を読み、次を警告する。
- FIRST: 最初の動きが --first 秒より後は警告、**ページ先頭の枚で --ng 秒（既定6秒）より後は NG**（タイトルだけの時間）
- GAP  : 動きと動きの間（前のフェードの終わり→次の開始）が --gap 秒より長い
- TAIL : 最後の動きから枚の終わりまでが --gap 秒より長い（無音の考える時間の枚は除く）

**無音フレーム**（STORYBOARD の voiceover が空）は見ない。ページの途中（transition_in: cut）の枚は前の絵が残るので FIRST は WARN、
ページの先頭（crossfade）の枚は FIRST が NG（タイトルだけの時間）。結果は目安で、語りが長く読む間（定義・計算の読み上げ）は
意図した間のこともある。最終判断はレビュー担当が画像で見る。
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

FADE = 0.4


def storyboard(unit: Path):
    sb = (unit / "STORYBOARD.md").read_text(encoding="utf-8")
    out = {}
    for m in re.finditer(r"^## Frame (\d+).*?\n(.*?)(?=^## Frame |\Z)", sb, re.S | re.M):
        body = m.group(2)
        vo = (re.search(r'^- voiceover: "(.*)"', body, re.M) or [None, ""])[1]
        tr = (re.search(r"^- transition_in: (\S+)", body, re.M) or [None, "cut"])[1]
        dur = float((re.search(r"^- duration: ([\d.]+)s", body, re.M) or [None, "0"])[1])
        src = (re.search(r"^- src: (\S+)", body, re.M) or [None, ""])[1]
        out[int(m.group(1))] = {"vo": vo.strip(), "tr": tr, "dur": dur, "src": src}
    return out


def starts(html: str):
    """(開始, 終わり) のリスト。フェード＝opacity 0→1、描画＝strokeDashoffset。矢じりのフェード（0.1秒）は描画に含める。"""
    ts = []
    for m in re.finditer(r'tl\.fromTo\("#[^"]+", \{ opacity: 0 \}, \{ opacity: 1, duration: ([\d.]+)[^}]*\}, ([\d.]+)\);', html):
        d, t = float(m.group(1)), float(m.group(2))
        if d >= 0.2:                       # 矢じり（0.1秒）は描画の一部
            ts.append((t, t + d))
    for m in re.finditer(r'strokeDashoffset: 0, duration: ([\d.]+)[^}]*\}, ([\d.]+)\);', html):
        d, t = float(m.group(1)), float(m.group(2))
        ts.append((t, t + d))
    return sorted(ts)


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("unit")
    ap.add_argument("--first", type=float, default=4.0, help="これより遅い最初の動きは警告")
    ap.add_argument("--ng", type=float, default=6.0, help="ページ先頭でこれより遅い最初の動きは NG")
    ap.add_argument("--gap", type=float, default=7.0)
    a = ap.parse_args(argv[1:])
    unit = Path(a.unit)
    sb = storyboard(unit)
    bad = 0
    for n in sorted(sb):
        f = sb[n]
        if not f["vo"]:
            continue                                    # 無音の考える時間
        # 2026-10-19: src は "compositions/frames/…" で、"com-position-s" に "position" が入り、全フレームを飛ばしていた。ファイル名だけで見る
        if "position" in f["src"].split("/")[-1]:
            continue                                    # 現在地は一覧が最初から見えていて、強調だけが後から付く
        html_path = unit / f["src"]
        if not html_path.is_file():
            continue
        ts = starts(html_path.read_text(encoding="utf-8"))
        page_head = f["tr"].startswith("crossfade") or n == 1
        msgs = []
        if not ts:
            msgs.append("動きが1つも無い")
        else:
            if ts[0][0] > a.first:
                ng = page_head and ts[0][0] > a.ng
                msgs.append(f"{'NG' if ng else 'warn'} FIRST 最初の動きが {ts[0][0]:.1f}s（警告 > {a.first}s / NG > {a.ng}s）" + ("＝ページの先頭でタイトルだけ" if ng else ""))
            for (s0, e0), (s1, _e1) in zip(ts, ts[1:]):
                if s1 - e0 > a.gap:
                    msgs.append(f"warn GAP {e0:.1f}s→{s1:.1f}s（{s1 - e0:.1f}s 増えない）")
            if f["dur"] - ts[-1][1] > a.gap + 1.2:
                msgs.append(f"warn TAIL 最後の動き {ts[-1][1]:.1f}s から枚の終わり {f['dur']:.1f}s まで {f['dur'] - ts[-1][1]:.1f}s")
        if msgs:
            bad += sum(1 for m in msgs if m.startswith("NG"))
            print(f"F{n:<2} ({f['src'].split('/')[-1]})")
            for m in msgs:
                print(f"    {m}")
    print(f"\n{unit.name}: NG {bad} 件" + ("（ページ先頭でタイトルだけの時間がある）" if bad else "（先頭の空白なし）"))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
