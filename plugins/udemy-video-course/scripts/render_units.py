# -*- coding: utf-8 -*-
"""ユニットを1本ずつ順にレンダリングし、字幕（手元の確認用）とクリックの検査まで回す。

    python render_units.py <unit> [<unit> ...]

- 1本ずつ順に回す（同時に回すとメモリが足りなくなる。ほかの重い処理と重ねない）
- 出力は `<unit>/renders/video.mp4`。ログは `<unit>/renders/render.log`（render_status.py が最後の行を出す）
- Hyperframes の版は `course.yaml` の hyperframes_version
- **1本ずつ前景で回す**（1本およそ3分・280秒の動画）。回す前に空きメモリを見る。7本まとめて裏で流したら、
  空き 4.5GB/32GB で2本目の途中にメモリ不足で止められた（AZ-104 L2-1。空き 15GB で1本ずつ回すと全部通った）
- 止められたら render_status.py で数える（止められたあとに「未レンダリング」と誤って報告したことがある）。
  止まったユニットの renders/ に .video.hf-transaction-* が残るが、次の書き出しは通る

終了コード: 0＝全部レンダリングできた／1＝どれかが失敗。最後に ALLDONE を出す。
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import course_config  # noqa: E402
from unit_build import env_for, tool  # noqa: E402

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    course = course_config.load()
    env = env_for(course)
    npx = tool("npx")
    failed = []
    for u in argv[1:]:
        unit = course.unit(u)
        print(f"== {unit.name}", flush=True)
        (unit / "renders").mkdir(exist_ok=True)
        with open(unit / "renders" / "render.log", "w", encoding="utf-8") as log:
            rc = subprocess.run([npx, "--yes", course.hyperframes, "render", "--skill=faceless-explainer",
                                 "--quality", "high", "--output", "renders/video.mp4"],
                                cwd=unit, env=env, stdout=log, stderr=subprocess.STDOUT).returncode
        print(f"render {rc}", flush=True)
        if rc != 0:
            failed.append(unit.name)
            continue
        for script, extra in (("make_srt.py", []), ("check_clicks.py", [])):
            r = subprocess.run([sys.executable, str(HERE / script), str(unit), *extra], env=env,
                               capture_output=True, text=True, encoding="utf-8", errors="replace")
            last = (r.stdout + r.stderr).strip().splitlines()
            print(last[-1] if last else f"{script}: 出力なし", flush=True)
    if failed:
        print(f"FAIL: レンダリングに失敗: {', '.join(failed)}（renders/render.log を見る）")
    print("ALLDONE")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
