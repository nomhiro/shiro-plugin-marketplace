"""講座テンプレートを展開して新しい試験対策プロジェクトを初期化する。

既存ファイルは絶対に上書きしない（skip して報告）。何度実行しても安全。
"""
from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path

# 直接実行（python .../scripts/x.py）でも兄弟モジュールを解決できるようにする。
# pytest からは scripts パッケージとして import されるため、その場合は何もしない。
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts._console import safe_stdout

PLACEHOLDERS = (
    "CERT_ID",
    "CERT_NAME",
    "VENDOR",
    "STUDY_GUIDE_URL",
    "EXAM_MINUTES",
    "PASS_SCORE",
    "MOCK_EXAMS",
    "QUESTIONS_PER_EXAM",
    "MODE",
)

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates" / "exam-course"
_TOKEN = re.compile(r"\{\{([A-Z_]+)\}\}")
# テンプレート段階で置換せずコピーする拡張子
_COPY_AS_IS = (".csv",)


class InitError(Exception):
    """テンプレート展開に失敗した。"""


def render(text: str, values: dict[str, str]) -> str:
    def sub(m: re.Match[str]) -> str:
        key = m.group(1)
        if key not in values:
            raise InitError(f"未知のプレースホルダ {{{{{key}}}}}")
        return str(values[key])

    return _TOKEN.sub(sub, text)


def _output_name(src: Path) -> str:
    name = src.name
    if name.endswith(".tmpl"):
        name = name[: -len(".tmpl")]
    if name == "gitignore":
        name = ".gitignore"
    return name


def _output_relpath(src: Path, tdir: Path) -> Path:
    """テンプレート内の相対パスを保ったまま出力先を決める。

    `research/AUTHORING-GUARDRAILS.md.tmpl` のようにサブディレクトリを持つ
    テンプレートがあるため、ファイル名だけでなく階層も維持する。
    """
    rel = src.relative_to(tdir)
    return rel.parent / _output_name(src)


def init_course(
    dest, values: dict[str, str], template_dir=None
) -> dict[str, list[str]]:
    dest = Path(dest)
    tdir = Path(template_dir) if template_dir else TEMPLATE_DIR
    if not tdir.is_dir():
        raise InitError(f"テンプレートディレクトリが無い: {tdir}")
    missing = [k for k in PLACEHOLDERS if k not in values]
    if missing:
        raise InitError(f"値が渡されていないプレースホルダ: {missing}")

    dest.mkdir(parents=True, exist_ok=True)
    created: list[str] = []
    skipped: list[str] = []

    for src in sorted(tdir.rglob("*")):
        if not src.is_file():
            continue
        rel = _output_relpath(src, tdir)
        out = dest / rel
        label = rel.as_posix()
        if out.exists():
            skipped.append(label)
            continue
        out.parent.mkdir(parents=True, exist_ok=True)
        if src.suffix in _COPY_AS_IS:
            shutil.copyfile(src, out)
        else:
            text = render(src.read_text(encoding="utf-8"), values)
            out.write_text(text, encoding="utf-8", newline="\n")
        created.append(label)

    return {"created": created, "skipped": skipped}


def main(argv: list[str]) -> int:
    safe_stdout()
    ap = argparse.ArgumentParser(description="試験対策講座プロジェクトを初期化する")
    ap.add_argument("--dest", required=True)
    ap.add_argument("--cert", required=True, help="試験番号 (例: CCA-F)")
    ap.add_argument("--cert-name", required=True, help="正式名称")
    ap.add_argument("--vendor", required=True)
    ap.add_argument("--study-guide", required=True)
    ap.add_argument("--exam-minutes", required=True)
    ap.add_argument("--pass-score", required=True)
    ap.add_argument("--mock-exams", default="6")
    ap.add_argument("--questions-per-exam", default="50")
    ap.add_argument(
        "--mode", default="mock-exam", choices=("mock-exam", "mixed"),
        help="mock-exam=全本同じ問題数のフル模試 / "
             "mixed=本ごとに問題数と配分が違う（分野別演習＋模試など）",
    )
    a = ap.parse_args(argv[1:])

    values = {
        "CERT_ID": a.cert,
        "CERT_NAME": a.cert_name,
        "VENDOR": a.vendor,
        "STUDY_GUIDE_URL": a.study_guide,
        "EXAM_MINUTES": a.exam_minutes,
        "PASS_SCORE": a.pass_score,
        "MOCK_EXAMS": a.mock_exams,
        "QUESTIONS_PER_EXAM": a.questions_per_exam,
        "MODE": a.mode,
    }
    try:
        result = init_course(a.dest, values)
    except InitError as e:
        print(f"FAIL: {e}")
        return 1

    for name in result["created"]:
        print(f"  created: {name}")
    for name in result["skipped"]:
        print(f"  skipped (already exists): {name}")
    print(f"OK: {len(result['created'])} created, {len(result['skipped'])} skipped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
