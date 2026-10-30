"""レクチャーの「区切りの札」プロジェクトを作る（2026-10-08・ユーザー指示「解説が次から次に進むと分かりづらい」）。

    python make_bridge.py 3-1 2 "分類と回帰,線形回帰と時系列,ロジスティック回帰,SVMとマージン最大化,決定木,アンサンブル学習"

→ `<videos_dir>/lecture-3-1-bridge-2/`（ユニット1とユニット2の間の1枚。「ここまでが〇〇でした。次は、△△です。」）

## 何を作るか（作るのは「入れ物」まで）

SCRIPT.md / BRIEF.md / STORYBOARD.md / slides.py と、雛形（`course.yaml` の template_dir）から写した枠組み（frame.md・設定・フォント）。
**音声・語末・レンダリングは作らない**（既存の手順で回す。下に出す「次」）。
既にあるディレクトリには何もしない（上書きしない）。

## 画面（`slide-format.md` §8）

タイトル「このレクチャーの流れ」＋流れの名前を**全部・縦1列**（冒頭の「流れ」と同じ）。
済みのユニットは ✓、「ここまで」の語末で直前が済みに、「次は」の語末で次が「いま」（青）になる。
（2026-10-08 受講者目線レビューで変更。以前は読む2つ以外を空の器にしていたが、全体のどこにいるか分からなかった）

## 語末の綴り

`slides.py` の `PHRASE_PREV` / `PHRASE_NEXT` は STT の綴りで引く（`.hyperframes/frame-packets/_beats.md`）。
STT が名前を違う綴りで返したら KeyError になり、**語の一覧が出る**ので、その綴りに直す。
"""

from __future__ import annotations

import datetime
import shutil
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
VIDEOS = COURSE.videos
TEMPLATE = COURSE.template   # 枠組みの写し元（フォント・frame.md・設定）
AUDIENCE = COURSE.audience
COPY = ["AGENTS.md", "CLAUDE.md", "frame.md", "hyperframes.json", "package.json"]

SLIDES_PY = '''"""L{lec} 区切りの札 #{n}（「{prev}」→「{nxt}」）— スライド型。`make_bridge.py` が作った。

    python unit_build.py lecture-{lec}-bridge-{n}     # slides.py は unit_build.py から流す（slide_kit をパスに入れる）

語末は `_beats.md`（実測 STT）から引く。**秒数をここに手書きしない。**
画面は流れの名前を全部（縦1列）。済み＝✓、次＝「いま」（2026-10-08 受講者目線レビュー・ユーザー承認）。
"""
import sys
from pathlib import Path

UNIT = Path(__file__).resolve().parent
from slide_kit import Slide, load_durations, Beats, bridge_rows  # noqa: E402

D = load_durations(UNIT)
E = Beats(UNIT)
OUT = UNIT / "compositions" / "frames"
OUT.mkdir(parents=True, exist_ok=True)

NAMES = {names!r}                  # 6つの名前（全部を縦1列で表示。語りで読むのは PREV と NEXT）
NEXT = {n}                         # 次に始まるユニットの番号（1 始まり）
# ★ STT の綴り（_beats.md の語を連結した形）。名前を違う綴りで返したら KeyError で語の一覧が出るので直す
PHRASE_PREV = {phrase_prev!r}
PHRASE_NEXT = {phrase_next!r}


def frame1():
    # 2026-10-08 受講者目線レビューで変更: 縦1列・6つの名前を全部表示（済み＝✓／直前→済み／次＝「いま」）。
    s = Slide(UNIT, "01-bridge", D[1], "このレクチャーの流れ")
    bridge_rows(s, NAMES, NEXT, E(1, PHRASE_PREV), E(1, PHRASE_NEXT))
    (OUT / f"{{s.id}}.html").write_text(s.html(), encoding="utf-8", newline="\\n")
    print(f"  {{s.id}}.html  reveals={{len(s.beats)}}  D={{s.duration:g}}s")


if __name__ == "__main__":
    frame1()
'''


def main(argv: list[str]) -> int:
    if len(argv) != 4:
        print(__doc__)
        return 2
    lec, n, names = argv[1], int(argv[2]), [x.strip() for x in argv[3].split(",")]
    if not 2 <= n <= len(names):
        print(f"FAIL: N は 2〜{len(names)}（最初のユニットの前には置かない）")
        return 2
    prev, nxt = names[n - 2], names[n - 1]
    unit = VIDEOS / f"lecture-{lec}-bridge-{n}"
    if not (TEMPLATE / "frame.md").is_file():
        print(f"FAIL: 雛形 {TEMPLATE} に frame.md が無い（course.yaml の template_dir）")
        return 1
    if unit.exists():
        print(f"FAIL: {unit} が既にある。上書きしない")
        return 1

    unit.mkdir(parents=True)
    for f in COPY:
        if (TEMPLATE / f).exists():
            shutil.copy2(TEMPLATE / f, unit / f)
    (unit / "assets" / "fonts").mkdir(parents=True)
    for f in sorted((TEMPLATE / "assets" / "fonts").glob("*")):
        if f.is_file():
            shutil.copy2(f, unit / "assets" / "fonts" / f.name)
    (unit / "meta.json").write_text(
        f'{{\n  "id": "lecture-{lec}-bridge-{n}",\n  "name": "lecture-{lec}-bridge-{n}",\n  "createdAt": "{datetime.date.today().isoformat()}T00:00:00.000Z"\n}}\n',
        encoding="utf-8", newline="\n")

    line = f"ここまでが、{prev}でした。次は、{nxt}です。"
    (unit / "SCRIPT.md").write_text(
        f"# SCRIPT — レクチャー {lec} の区切り #{n}（{prev} → {nxt}）\n\n"
        f"> 台本の正本は `lectures/` の L{lec} レクチャー枠 doc「1.4 区切り」。ここは音声の入力（字下げ行だけを読む）。\n\n"
        f"## Line 1 — 区切り (Frame 1)\n\n    {line}\n", encoding="utf-8", newline="\n")
    (unit / "BRIEF.md").write_text(
        f"---\nworkflow: faceless-explainer\nflow: automation\nstoryboard: no\nmessage: \"区切り（{prev}→{nxt}）\"\n"
        f"topic: レクチャー{lec}の区切り #{n}\nangle: concept\ndestination: udemy\naspect: 16:9\nlanguage: ja\n"
        f"audience: {AUDIENCE}\nlength: 10s\nvoice_gender: female\n---\n\n## Intent\n\n"
        f"レクチャー L{lec} の**ユニット間の区切りの札**（{prev} → {nxt}）。台本の正本はレクチャー枠 doc「1.4 区切り」。\n"
        "スライド型（プラグインの `references/slide-format.md` §8）。画面は流れの名前を全部（縦1列）。語りで読むのは2つ。\n",
        encoding="utf-8", newline="\n")
    (unit / "STORYBOARD.md").write_text(
        f"---\nformat: 1920x1080\nduration: 10s\nmessage: \"区切り（{prev}→{nxt}）\"\narc: concept-explainer\n"
        f"audience: {AUDIENCE}\nmode: autonomous\nmusic: none\n---\n\n> スライド型。1枚だけなので cut。\n\n"
        f"## Frame 1 — 区切り\n\n- scene: 区切り（{prev} → {nxt}）\n- voiceover: \"{line}\"\n- duration: 8s\n"
        "- transition_in: cut\n- status: built\n- src: compositions/frames/01-bridge.html\n- type: overview\n",
        encoding="utf-8", newline="\n")
    # 台本の綴りを STT が返す綴りの初期値にする（違えば KeyError で語の一覧が出る）
    (unit / "slides.py").write_text(
        SLIDES_PY.format(lec=lec, n=n, prev=prev, nxt=nxt, names=names, phrase_prev=prev, phrase_next=nxt),
        encoding="utf-8", newline="\n")
    (unit / "compositions" / "frames").mkdir(parents=True)

    print(f"OK: {unit}\n  台本: {line}")
    print(
        "次（この順。`--help` は使わない）:\n"
        f"  python tts.py {unit.name}                      # 音声（作った直後に退避する）\n"
        f"  python check_reading.py {unit.name} / python check_clicks.py {unit.name} --wav-only\n"
        f"  python pad_audio.py {unit.name} / python make_beats.py {unit.name}\n"
        "  node <faceless_scripts>/audio.mjs sync-durations --audio-meta ./audio_meta.json --storyboard ./STORYBOARD.md   # プロジェクト内で\n"
        f"  python unit_build.py {unit.name} → python render_units.py {unit.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
