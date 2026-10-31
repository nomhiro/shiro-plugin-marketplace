"""ユニットの台本に、語りの行（＝フレーム）を途中に足し、後ろの番号を全部ずらす（2026-10-31 新設。AZ-104 L2-1 で
座学に画面の枚を後から10枚足したときに作った。`references/slide-format.md` §2g）。

    python insert_line.py videos/<unit> <spec.json> [--dry-run]     # 講座の直下で。まず --dry-run で旧→新を見る

足す位置は**ページの切れ目**（PAGES の1行の途中に入れない）。足す前に SCRIPT.md・slides.py・audio_meta.json・assets/voice を退避する。
足したあとは: tts.py --only <新しい番号> → 読みの確認 → pad_audio → make_beats（全行の STT をやり直すので古い枚の E() も検査で確かめる）
→ new_storyboard（PAGES の順の id）→ sync-durations → 考える時間の枚を 6s → unit_build。

spec.json: [{"after": 5, "title": "画面：継承を見分ける", "delivery": "…", "text": "…"}, …]
  after は**いまの**番号（足す前の番号）。大きい順に処理するので、互いの番号を気にしなくてよい。

ずらすもの（番号 ≥ after+1 を +1）:
  - SCRIPT.md の `## Line N — … (Frame N)` と `## Frame N — …`（無音の枚）
  - assets/voice/NN.wav（大きい番号から改名して衝突させない）
  - audio_meta.json の voices[].frame と path
  - slides.py の E(N, …)・`def fN(`・`fN` の参照・PAGES の (N, "NN-名前", fN)
  - compositions/frames/*.html は消す（古い番号の HTML が assemble-index に拾われる）
足した行の音声は無い → `tts.py --only <新しい番号>` で作る。足した行の slides.py の関数と PAGES の行は手で書く。
番号の対応（旧 → 新）を <unit-dir>/.hyperframes/renumber.json に書く（after-tts の退避は旧の番号のまま）。
"""
import json
import re
import shutil
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass


def shift(n: int, k: int) -> int:
    return n + 1 if n >= k else n


def main(argv):
    unit = Path(argv[1]).resolve()
    spec = json.loads(Path(argv[2]).read_text(encoding="utf-8"))
    dry = "--dry-run" in argv
    script = (unit / "SCRIPT.md").read_text(encoding="utf-8")
    slides = (unit / "slides.py").read_text(encoding="utf-8")
    meta = json.loads((unit / "audio_meta.json").read_text(encoding="utf-8"))
    voice = unit / "assets" / "voice"
    nmax = max(int(m) for m in re.findall(r"^## (?:Line|Frame) (\d+)", script, re.M))
    mapping = {n: n for n in range(1, nmax + 1)}
    renames = []
    for ins in sorted(spec, key=lambda s: -s["after"]):
        k = ins["after"] + 1

        def h(m):
            n = int(m.group(2))
            n2 = shift(n, k)
            s = f"## {m.group(1)} {n2}{m.group(3)}"
            return s.replace(f"(Frame {n})", f"(Frame {n2})")
        script = re.sub(r"^## (Line|Frame) (\d+)( —[^\n]*)", h, script, flags=re.M)
        block = (f"## Line {k} — {ins['title']} (Frame {k})\n\n**Delivery:** {ins['delivery']}\n\n"
                 f"    {ins['text']}\n\n")
        m = re.search(rf"^## (?:Line|Frame) {k + 1} —", script, re.M)
        if m:
            script = script[:m.start()] + block + script[m.start():]
        else:
            script = script.rstrip("\n") + "\n\n" + block
        # slides.py
        slides = re.sub(r"\bE\((\d+)", lambda m: f"E({shift(int(m.group(1)), k)}", slides)
        # PAGES の (N, "NN-名前", … の番号だけ。fN は下の1回でまとめてずらす（2回ずらさない）
        slides = re.sub(r"\(\s*(\d+),\s*\"(\d+)-([^\"]+)\",",
                        lambda m: f'({shift(int(m.group(1)), k)}, "{shift(int(m.group(2)), k):02d}-{m.group(3)}",', slides)
        # def fN( ・呼び出し fN(s) ・PAGES の fN をまとめて
        slides = re.sub(r"(?<![\w\"'])f(\d+)\b", lambda m: f"f{shift(int(m.group(1)), k)}", slides)
        # audio_meta
        for v in meta["voices"]:
            if v.get("frame") is not None:
                n2 = shift(int(v["frame"]), k)
                v["frame"] = n2
                v["path"] = f"assets/voice/{n2:02d}.wav"
        mapping = {old: shift(new, k) for old, new in mapping.items()}
        renames.append(k)
    # wav の改名（旧番号 → 新番号。大きい番号から）
    moves = sorted(((o, n) for o, n in mapping.items() if o != n and (voice / f"{o:02d}.wav").exists()), reverse=True)
    print("旧→新:", {o: n for o, n in mapping.items() if o != n})
    print("足した行:", sorted(set(range(1, nmax + len(spec) + 1)) - set(mapping.values())))
    if dry:
        return
    for o, n in moves:
        (voice / f"{o:02d}.wav").rename(voice / f"{n:02d}.wav")
    (unit / "SCRIPT.md").write_text(script, encoding="utf-8")
    (unit / "slides.py").write_text(slides, encoding="utf-8")
    (unit / "audio_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    fr = unit / "compositions" / "frames"
    if fr.exists():
        for f in fr.glob("*.html"):
            f.unlink()
    (unit / ".hyperframes").mkdir(exist_ok=True)
    (unit / ".hyperframes" / "renumber.json").write_text(json.dumps(mapping, indent=1), encoding="utf-8")
    print("ok")


if __name__ == "__main__":
    main(sys.argv)
