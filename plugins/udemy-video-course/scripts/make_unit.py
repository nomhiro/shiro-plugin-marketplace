"""新しいユニット（1ユニット＝1レクチャー）の入れ物を作る。

    python make_unit.py <slug> "<日本語タイトル>" <lecture-doc-id>
    例: python make_unit.py genai-risks "生成 AI のリスクと限界" L1-1-1

作るもの（既にあるファイルは上書きしない）:
- <videos_dir>/<slug>/ … frame.md・設定・フォント（<template_dir> から写す）、BRIEF.md・SCRIPT.md・STORYBOARD.md の雛形、空の compositions/frames
- <lectures_dir>/<章フォルダ>/<doc-id>_<種別>_<slug>.md … ユニット doc の雛形（§5 は `slide_table.py --write` で後から書き出す）
  章フォルダは doc-id の章番号 L<章>-… から、`course.yaml` の chapter_dirs で決める。
  種別は doc_kind_tokens（冒頭・末尾の lecture-… は frame、名前が handson_suffix で終わるものは handson、ほかは lecture）

講座の値（受講者像・章フォルダ・雛形の場所）は `course.yaml`（course_config.py）から読む。
音声以降はプラグインの `references/unit-playbook.md` の手順。
"""
import datetime
import re
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
ROOT = COURSE.root
COPY = ["AGENTS.md", "CLAUDE.md", "frame.md", "hyperframes.json", "package.json"]
# 雛形の assets/fonts/ はフォルダごと写す（書体の名前を道具に埋めない）

# 実践の本体の Line 1 の型。講座で `handson_line1` を書けばそれを使う（入れ忘れが続いたので雛形に置く）
HANDSON_LINE1 = ("では、手を動かしましょう。このレッスンのREADMEに沿って進めます。"
                 "手順は、Nつです。冒頭で見た流れに沿って、進めます。手順1で、…")


def chapter_dir(doc_id: str) -> str:
    """doc-id（L1-1-2 / L1-1 / L99-1-1）の章番号から lectures/ 下のフォルダ名を返す。"""
    dirs = COURSE.chapter_dirs
    m = re.match(r"L(\d+)", doc_id)
    if not m:
        raise SystemExit(f"doc-id の形が違う: {doc_id}（例: L1-1-2）")
    if not dirs:
        return f"{int(m.group(1)):02d}"
    if int(m.group(1)) not in dirs:
        raise SystemExit(f"章 {m.group(1)} が course.yaml の chapter_dirs に無い: {doc_id}")
    return dirs[int(m.group(1))]


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        return str(path)


def put(path: Path, text: str):
    if path.exists():
        print(f"  既にある（そのまま）: {rel(path)}")
        return
    path.write_text(text, encoding="utf-8", newline="\n")
    print(f"  作成: {rel(path)}")


def main(argv):
    if len(argv) < 4:
        print(__doc__)
        return 2
    slug, title, doc_id = argv[1], argv[2], argv[3]
    tpl = COURSE.template
    if not (tpl / "frame.md").is_file():
        print(f"FAIL: 雛形 {rel(tpl)} に frame.md が無い（course.yaml の template_dir）")
        return 1
    audience = COURSE.audience
    handson = slug.endswith(COURSE.data["handson_suffix"])
    u = COURSE.videos / slug
    (u / "compositions" / "frames").mkdir(parents=True, exist_ok=True)
    for f in COPY:
        if (tpl / f).exists() and not (u / f).exists():
            shutil.copy2(tpl / f, u / f)
    fonts = tpl / "assets" / "fonts"
    if fonts.is_dir():
        (u / "assets" / "fonts").mkdir(parents=True, exist_ok=True)
        for f in fonts.iterdir():
            if f.is_file() and not (u / "assets" / "fonts" / f.name).exists():
                shutil.copy2(f, u / "assets" / "fonts" / f.name)
    fmt = COURSE.data.get("slide_format_doc") or "プラグインの references/slide-format.md"
    put(u / "meta.json", f'{{\n  "id": "{slug}",\n  "name": "{slug}",\n  "createdAt": "{datetime.date.today().isoformat()}T00:00:00.000Z"\n}}\n')
    put(u / "BRIEF.md",
        f"---\nworkflow: faceless-explainer\nflow: automation\nstoryboard: no\nmessage: \"{title}\"\ntopic: {title}\nangle: concept\n"
        f"destination: udemy\naspect: 16:9\nlanguage: ja\naudience: {audience}\nlength: 240s\nvoice_gender: female\n---\n\n"
        f"## Intent\n\n{title}（型は `{fmt}`）。\n")
    put(u / "STORYBOARD.md",
        f"---\nformat: 1920x1080\nduration: 240s\nmessage: \"{title}\"\narc: concept-explainer\naudience: {audience}\nmode: autonomous\nmusic: none\n---\n\n"
        "> 雛形。`python new_storyboard.py <slug> <id...>` で作り直す。\n\n## Frame 1 — 雛形\n\n- scene: -\n- voiceover: \"\"\n- duration: 5s\n"
        "- transition_in: cut\n- status: built\n- src: compositions/frames/01-position.html\n- type: hook\n")
    line1 = COURSE.data.get("handson_line1") or HANDSON_LINE1
    put(u / "SCRIPT.md",
        f"# SCRIPT — {slug}（{title}）\n\n**Voice:** {COURSE.tts('voice')} (Google Gemini-TTS)\n\n"
        "> 音声の入力は**字下げ行（半角スペース4つ）だけ**。`## Line N — 名前 (Frame N)` の見出しとフレーム番号が wav 番号になる。\n\n"
        + (f"## Line 1 — 手順1 (Frame 1)\n\n**Delivery:** 落ち着いて。\n\n    {line1}\n\n" if handson else ""))
    kinds = COURSE.data["doc_kind_tokens"]
    token = kinds.get("frame", "") if slug.startswith("lecture-") else kinds.get("handson", "") if handson else kinds.get("lecture", "")
    doc = COURSE.lectures / chapter_dir(doc_id) / f"{doc_id}_{token}{slug}.md"
    doc.parent.mkdir(parents=True, exist_ok=True)
    refs = COURSE.data.get("doc_refs") or []
    put(doc,
        f"# {doc_id} {title}\n\n> 1ユニット＝1レクチャー。台本の正本は `{rel(u)}/SCRIPT.md`。絵と語りの対応（§5）は slides から自動で書き出す。\n\n"
        "## このユニットのゴール\n\n（台本ができたら、受講者ができるようになることを2〜3行で書く）\n\n"
        f"## 5. 図解（スライド）の要求\n\n（`python slide_table.py {rel(u)} --write {rel(doc)}` で書き出す）\n\n"
        "## 参照\n\n" + "".join(f"- `{r}`\n" for r in refs))
    print(f"OK: {rel(u)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
