"""sections.md の YAML front matter（試験プロファイル）を読み取り検証する。

harness の唯一の入力インターフェース。資格固有の情報はすべてここから来る。
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

# 直接実行（python .../scripts/x.py）でも兄弟モジュールを解決できるようにする。
# pytest からは scripts パッケージとして import されるため、その場合は何もしない。
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts._console import safe_stdout

VENDORS = ("anthropic", "microsoft", "github", "cloudflare", "ipa", "generic")
MODES = ("mock-exam",)

REQUIRED_TOP = (
    "cert", "cert_name", "vendor", "study_guide", "mode",
    "exam", "mock_exams", "questions_per_exam",
    "question_types", "primary_sources", "domains",
)
REQUIRED_EXAM = ("minutes", "pass_score", "language")
REQUIRED_DOMAIN = ("id", "name", "ratio", "per_exam")


class ProfileError(Exception):
    """front matter が読めない・壊れている。"""


def load_profile(sections_md) -> dict:
    path = Path(sections_md)
    text = path.read_text(encoding="utf-8-sig")
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ProfileError(f"{path}: front matter の開始 '---' が先頭行にない")
    try:
        end = next(i for i, l in enumerate(lines[1:], 1) if l.strip() == "---")
    except StopIteration:
        raise ProfileError(f"{path}: front matter の終端 '---' が見つからない") from None
    try:
        data = yaml.safe_load("\n".join(lines[1:end]))
    except yaml.YAMLError as e:
        raise ProfileError(f"{path}: front matter の YAML 解析に失敗: {e}") from e
    if not isinstance(data, dict):
        raise ProfileError(f"{path}: front matter がマッピングではない")
    return data


def validate_profile(profile: dict) -> list[str]:
    errs: list[str] = []

    for key in REQUIRED_TOP:
        if key not in profile:
            errs.append(f"必須キー '{key}' がない")

    vendor = profile.get("vendor")
    if vendor is not None and vendor not in VENDORS:
        errs.append(f"vendor '{vendor}' は未対応。{VENDORS} のいずれかにする")

    mode = profile.get("mode")
    if mode is not None and mode not in MODES:
        errs.append(f"mode '{mode}' は未対応。現状 {MODES} のみサポート")

    exam = profile.get("exam")
    if isinstance(exam, dict):
        for key in REQUIRED_EXAM:
            if key not in exam:
                errs.append(f"必須キー 'exam.{key}' がない")
    elif "exam" in profile:
        errs.append("exam がマッピングではない")

    for key in ("mock_exams", "questions_per_exam"):
        val = profile.get(key)
        if val is not None and (not isinstance(val, int) or val < 1):
            errs.append(f"{key} は 1 以上の整数にする（現在: {val!r}）")

    domains = profile.get("domains")
    if not isinstance(domains, list) or not domains:
        if "domains" in profile:
            errs.append("domains が非空のリストではない")
        return errs

    seen: set[str] = set()
    total = 0
    for i, d in enumerate(domains, 1):
        if not isinstance(d, dict):
            errs.append(f"domains[{i}] がマッピングではない")
            continue
        for key in REQUIRED_DOMAIN:
            if key not in d:
                errs.append(f"domains[{i}] に必須キー '{key}' がない")
        did = d.get("id")
        if did in seen:
            errs.append(f"domains[{i}]: duplicate domain id '{did}'")
        if did is not None:
            seen.add(did)
        per = d.get("per_exam")
        if isinstance(per, int):
            total += per
        elif per is not None:
            errs.append(f"domains[{i}]: per_exam が整数ではない（{per!r}）")

    qpe = profile.get("questions_per_exam")
    if isinstance(qpe, int) and total != qpe:
        errs.append(f"per_exam の合計 {total} が questions_per_exam {qpe} と一致しない")

    return errs


def domain_quota(profile: dict) -> dict[str, int]:
    return {d["id"]: d["per_exam"] for d in profile["domains"]}


def domain_names(profile: dict) -> dict[str, str]:
    return {d["id"]: d["name"] for d in profile["domains"]}


def main(argv: list[str]) -> int:
    safe_stdout()
    if len(argv) != 2:
        print("usage: profile.py <sections.md>", file=sys.stderr)
        return 2
    try:
        profile = load_profile(argv[1])
    except ProfileError as e:
        print(f"FAIL: {e}")
        return 1
    errs = validate_profile(profile)
    if errs:
        print(f"FAIL: {len(errs)} error(s)")
        for e in errs:
            print(f"  - {e}")
        return 1
    q = domain_quota(profile)
    print(
        f"OK: {profile['cert']} / mode={profile['mode']} / "
        f"{profile['mock_exams']} exams x {profile['questions_per_exam']} questions / "
        f"quota={q}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
