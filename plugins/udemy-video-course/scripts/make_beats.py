"""`word_times.py` の実測から、frame worker に配る `_beats.md` を作る。

    python make_beats.py videos/<unit>

`frame-packets.mjs` は「担当フレームのブロック」しか配らず、**語末の実測時刻はパケットに入らない**。
だから親が `_beats.md` を作って全員に読ませる（CLAUDE.md「ワーカーへの指示に必ず入れる5項目」の 0）。

出力: `videos/<unit>/.hyperframes/frame-packets/_beats.md`

★ 音声を作り直したら（`tts.py` の再実行）、**語末時刻は必ず変わる**（TTS は非決定的）。
  このツールを再実行して表を作り直し、旧→新の差を全ワーカーへ配る。
"""

from __future__ import annotations

import json
import re
import subprocess
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

HEAD = """# 実測の発話時刻とビートの置き方（{unit}）

**`word_times.py`（Google Speech-to-Text）の実測。** 図解のビートはこの表から逆算する。

## ★ 使い方の鉄則

1. **終了時刻だけを使う。開始時刻は使わない。**
   STT の開始時刻は**直前の無音を巻き込む**。**語が鳴り終わった時刻が信頼できる唯一の値。**
   **分解能は 0.1s。**
2. **字数按分でビートを置かない。**
   `BASE + chars * SEC_PER_CHAR` 型の式は、**同字数のかたまりの間隔が構造的に必ず等しくなる。**
   実測では同じ2字でも 0.10s と 1.20s の差がある。**定数の調整では表現できない。**
3. **実測値はスクリプト冒頭の1箇所に集約する。** 同じ数字を複数箇所に書くと次の再同期でずれる。
   ```js
   var W = {{ bins: 2.00, fade: 4.30, want: 6.30, end: 7.00 }};   /* ← 1箇所だけ */
   ```
4. **要素が「出終わっている」べき時刻を、語の終了時刻に合わせる。**
   語が鳴り始めてから動き出すと遅れて見える。**語の終了に着地を合わせる。**
5. **STT の書き起こしの「誤字」は TTS の誤読ではない**（汎化→繁華、境界→教会、写し→移し、いちばん→一番）。
   **時刻は正しい。** 語の綴りだけ台本で読み替える。
6. **音声は非決定的で再生成できない。** 尺が変わったら、この表を作り直して時刻だけ取り直す（幾何は変えない）。

"""


def parse(text: str):
    frames: dict[int, dict] = {}
    cur = None
    for line in text.splitlines():
        m = re.match(r"=== frame (\d+) ===", line.strip())
        if m:
            cur = int(m.group(1))
            frames[cur] = {"script": "", "w": []}
            continue
        if cur is None:
            continue
        if line.strip().startswith("台本:"):
            frames[cur]["script"] = line.strip()[3:].strip()
            continue
        m = re.match(r"\s+([\d.]+)s 〜\s+([\d.]+)s\s+(.+)", line)
        if m:
            frames[cur]["w"].append((float(m.group(1)), float(m.group(2)), m.group(3).strip()))
    return frames


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    unit = COURSE.unit(argv[1])
    meta_path = unit / "audio_meta.json"
    if not meta_path.exists():
        print("FAIL: %s がありません" % meta_path)
        return 1
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    dur = {v["frame"]: v["duration_s"] for v in meta["voices"]}

    print("word_times.py を実行（Speech-to-Text）…")
    r = subprocess.run(
        [sys.executable, str(Path(__file__).resolve().parent / "word_times.py"), str(unit)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if r.returncode != 0:
        print(r.stdout[-2000:], r.stderr[-2000:])
        return 1
    frames = parse(r.stdout)
    if not frames:
        print("FAIL: 語の時刻が取れなかった")
        return 1

    out = [HEAD.format(unit=unit.name)]
    for f in sorted(frames):
        out.append("## Frame %d — %.3fs" % (f, dur.get(f, 0.0)))
        out.append("")
        out.append("**台本**: " + frames[f]["script"])
        out.append("")
        out.append("```")
        for s, e, w in frames[f]["w"]:
            out.append("    %.2fs 〜 %5.2fs  %s" % (s, e, w))
        out.append("```")
        out.append("")

    silent = sorted(set(range(1, 10)) - set(frames))
    if silent:
        out.append("---")
        out.append("")
        out.append("## ★ 無音のフレーム: %s（`voiceover: \"\"`）" % ", ".join("F%d" % x for x in silent))
        out.append("")
        out.append("音声は無い。**台詞に乗せる根拠が無い**ので、ビートは**構造**で決める。")
        out.append("`transition_in: crossfade` なら **`0 → 0.5s` に tween を置かず**、動きは 0.5s 以降に始める。")
        out.append("")

    dest = unit / ".hyperframes" / "frame-packets"
    dest.mkdir(parents=True, exist_ok=True)
    b = "\n".join(out).encode("utf-8")
    (dest / "_beats.md").write_bytes(b)
    print("OK: %s を書きました（%d フレーム / %d bytes）" % (dest / "_beats.md", len(frames), len(b)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
