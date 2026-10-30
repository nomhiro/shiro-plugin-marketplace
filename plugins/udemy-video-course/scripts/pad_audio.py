"""行頭・行末に無音を足して、スライドの切り替えに「間」を作る（2026-09-22）。

    python pad_audio.py videos/<unit>                 # 既定: 行頭 0.6 秒・行末 1.2 秒
    python pad_audio.py videos/<unit> --head 0.6 --tail 1.2

## なぜ再生成しないのか

Gemini-TTS は非決定的で、**再生成すると全フレームの語末時刻が変わる**（CLAUDE.md 参照）。
「切り替えが速い」は**発話の外側の無音**の問題なので、**発話のバイトは1つも変えず、
ゼロ（無音）を前後に足すだけ**で直せる。ヘッダをゼロ埋めで直したときと同じ発想。

- 行末の無音 … 生成時に `tts.py` が 0.35 秒を足している。`--tail` は**総量**なので、足すのは `tail - 0.35`
- 行頭の無音 … 新しいスライドが見えてから語り始めるまでの間。語の時刻は**一律に `head` だけ後ろへずれる**
  （`slides.py` は `audio_meta.json` の `head_s` を読んで足すので、手で直さない）

## 冪等

`audio_meta.json` の `voices[]` に `head_s` があれば**触らない**（二重に足さない）。
足した行には `head_s` / `tail_s` を書く。`duration_s` は新しい実尺に更新する
（`audio.mjs sync-durations` がそれを STORYBOARD へ写す）。

## 退避

書き換える前に元の wav を `<audio_backup_dir>/<日付>/<unit>/pad-before/`（`course.yaml`。既定 videos/_audio-backup）へ写す（既にあれば上書きしない）。
"""

from __future__ import annotations

import argparse
import datetime
import json
import shutil
import sys
import time
import wave
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

BAKED_TAIL = 0.35   # tts.py の LINE_TAIL_SECONDS（生成時に焼き込まれている行末の無音）


def read_pcm(path: Path) -> tuple[bytes, int]:
    with wave.open(str(path), "rb") as w:
        assert w.getnchannels() == 1 and w.getsampwidth() == 2, f"{path}: 24kHz/mono/16bit 以外は扱わない"
        return w.readframes(w.getnframes()), w.getframerate()


def write_pcm(path: Path, pcm: bytes, rate: int) -> float:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    return len(pcm) / 2 / rate


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="音声の行頭・行末に無音を足す")
    ap.add_argument("project")
    ap.add_argument("--head", type=float, default=0.6, help="行頭の無音（秒）")
    ap.add_argument("--tail", type=float, default=1.2, help="行末の無音の総量（秒。生成時の 0.35 を含む）")
    a = ap.parse_args(argv[1:])
    if a.tail < BAKED_TAIL:
        print(f"FAIL: --tail は {BAKED_TAIL} 以上（生成時に焼き込まれた無音より短くはできない）")
        return 1

    project = Path(a.project).resolve()
    meta_path = project / "audio_meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import course_config

    backup = course_config.load().path("audio_backup_dir") / datetime.date.today().isoformat() / project.name / "pad-before"

    done = skipped = 0
    for v in meta["voices"]:
        if v.get("head_s") is not None:
            skipped += 1
            continue
        wav = project / v["path"]
        pcm, rate = read_pcm(wav)
        backup.mkdir(parents=True, exist_ok=True)
        if not (backup / wav.name).exists():
            shutil.copy2(wav, backup / wav.name)
        z = lambda sec: b"\x00" * (int(round(rate * sec)) * 2)
        new = z(a.head) + pcm + z(a.tail - BAKED_TAIL)
        old_dur = len(pcm) / 2 / rate
        dur = round(write_pcm(wav, new, rate), 3)
        assert new[len(z(a.head)):len(z(a.head)) + len(pcm)] == pcm, "発話のバイトが変わった"
        v.update({"head_s": a.head, "tail_s": a.tail, "duration_s": dur})
        print(f"  frame {v['frame']:>2}: {old_dur:>6.3f}s → {dur:>6.3f}s  (行頭 +{a.head} / 行末 +{a.tail - BAKED_TAIL:.2f})")
        done += 1

    # 2026-10-23 L4-3・L4-4: Windows でまれに Errno 22 になり、wav は足したのに head_s が残らず、やり直すと間が二重になった。待って書き直す
    for k in range(15):
        try:
            meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
            break
        except OSError:
            if k == 14:
                raise
            time.sleep(2)
    print(f"\nOK: {done} 行を足した / {skipped} 行は足し済みで据え置き。退避: {backup}")
    print("次: node $SKILL/scripts/audio.mjs sync-durations --audio-meta ./audio_meta.json --storyboard ./STORYBOARD.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
