# -*- coding: utf-8 -*-
"""1ユニットを組んで検査する（レンダリングはしない。最後にまとめて render_units.py で回す）。

    python unit_build.py <unit> [<unit> ...]      # ユニットの名前か、videos/<unit> のパス

順に: slides.py → assemble-index → transitions inject / verify → hyperframes lint / check → check_crossfade
→ snapshot（shot_times.py の時刻。各フレーム3枚）。どこかで失敗したら、そのユニットで止まる。

- slides.py は、この scripts フォルダと講座の部品フォルダ（`course.yaml` の parts_dir。既定 videos/_shared）を
  PYTHONPATH に入れて流す。slides.py の中で slide_kit の場所を書かなくてよい
- assemble-index.mjs・transitions.mjs は faceless-explainer のスキルのもの（`course.yaml` の faceless_scripts）
- Hyperframes は `course.yaml` の hyperframes_version に固定する（講座の途中で版を変えると描画が変わる）

終了コード: 0＝全部通った／1＝どれかで失敗／2＝引数・前提の不足。
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import course_config  # noqa: E402

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass


def tool(name: str) -> str:
    """Windows の npx / node は .cmd なので、場所を引いてから呼ぶ。"""
    found = shutil.which(name)
    if not found:
        raise SystemExit(f"FAIL: {name} が PATH に無い")
    return found


def env_for(course: course_config.Course) -> dict:
    parts = course.root / str(course.data.get("parts_dir") or "videos/_shared")
    paths = [str(HERE), str(parts)] + [p for p in os.environ.get("PYTHONPATH", "").split(os.pathsep) if p]
    return {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONPATH": os.pathsep.join(paths)}


def run(cmd: list[str], cwd: Path, env: dict, tail: int = 2, keep=None) -> int:
    r = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
    lines = (r.stdout + r.stderr).strip().splitlines()
    if keep:
        lines = [x for x in lines if keep(x)]
    for x in lines[-tail:] if tail else []:
        print(f"    {x}")
    return r.returncode


def build(course: course_config.Course, unit: Path) -> int:
    env = env_for(course)
    fs = course.faceless_scripts
    hf = course.hyperframes
    npx, node = tool("npx"), tool("node")
    print(f"== {unit.name}")
    # 生成の3段は、失敗したらそのユニットで止まる
    steps = [
        ("slides.py", [sys.executable, "slides.py"], 3),
        ("assemble-index", [node, str(fs / "assemble-index.mjs"), "--storyboard", "./STORYBOARD.md", "--hyperframes", "."], 0),
        ("transitions inject", [node, str(fs / "transitions.mjs"), "inject", "--storyboard", "./STORYBOARD.md", "--hyperframes", "."], 0),
    ]
    for label, cmd, tail in steps:
        print(f"  {label}")
        if run(cmd, unit, env, tail) != 0:
            print(f"FAIL: {unit.name}: {label}")
            return 1
    # 検査の段は結果の行を出すだけで止めない（警告でも 0 以外を返すものがある）。出た行を読んで直す
    checks = [
        ("transitions verify", [node, str(fs / "transitions.mjs"), "verify", "--storyboard", "./STORYBOARD.md", "--index", "./index.html"], 1, None),
        ("lint", [npx, "--yes", hf, "lint"], 2, None),
        ("check", [npx, "--yes", hf, "check"], 6, lambda x: any(k in x for k in ("error", "✗", "passed", "failed"))),
        ("check_crossfade", [sys.executable, str(HERE / "check_crossfade.py"), "."], 2, None),
    ]
    for label, cmd, tail, keep in checks:
        print(f"  {label}")
        run(cmd, unit, env, tail, keep)
    t = subprocess.run([sys.executable, str(HERE / "shot_times.py"), "."], cwd=unit, env=env,
                       capture_output=True, text=True, encoding="utf-8").stdout.strip()
    shutil.rmtree(unit / "snapshots", ignore_errors=True)
    subprocess.run([npx, "--yes", hf, "snapshot", "--at", t], cwd=unit, env=env, capture_output=True)
    n = len(list((unit / "snapshots").glob("*"))) if (unit / "snapshots").is_dir() else 0
    print(f"  snapshots: {n} 枚")
    return 0


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    course = course_config.load()
    if not (course.faceless_scripts / "assemble-index.mjs").is_file():
        print(f"FAIL: {course.faceless_scripts}/assemble-index.mjs が無い（faceless-explainer のスキルと course.yaml の faceless_scripts）")
        return 2
    for u in argv[1:]:
        unit = course.unit(u)
        if not (unit / "slides.py").is_file():
            print(f"FAIL: {unit}/slides.py が無い")
            return 2
        if build(course, unit) != 0:
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
