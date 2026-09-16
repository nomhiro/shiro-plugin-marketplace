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
MODES = ("mock-exam", "mixed")
# mixed モードの各セクションの種別
#   drill = 分野別演習（ドメインを絞れる・時間は緩め）
#   mock  = 本番相当のフル模試（全ドメイン横断）
SECTION_KINDS = ("drill", "mock")
REQUIRED_SECTION = ("slug", "title", "kind", "questions", "minutes")

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

    if profile.get("mode") == "mixed":
        errs.extend(_validate_sections(profile, seen, total))

    return errs


def _validate_sections(profile: dict, domain_ids: set, global_total: int) -> list:
    """mixed モードの sections を検証する。

    mock-exam モードは「N本すべて同じ問題数のフル模試」なので
    domains[].per_exam だけで表現できる。mixed は本ごとに問題数もドメイン配分も
    違うため、sections が本ごとの Source of Truth になる。
    """
    errs = []
    sections = profile.get("sections")
    if not isinstance(sections, list) or not sections:
        return ["mode: mixed では sections が非空のリストである必要がある"]

    want = profile.get("mock_exams")
    if isinstance(want, int) and len(sections) != want:
        errs.append(f"sections が {len(sections)} 件だが mock_exams は {want}")

    slugs = set()
    for i, sec in enumerate(sections, 1):
        if not isinstance(sec, dict):
            errs.append(f"sections[{i}] がマッピングではない")
            continue
        for key in REQUIRED_SECTION:
            if key not in sec:
                errs.append(f"sections[{i}] に必須キー '{key}' がない")

        slug = sec.get("slug")
        if slug in slugs:
            errs.append(f"sections[{i}]: duplicate slug '{slug}'")
        if slug is not None:
            slugs.add(slug)

        kind = sec.get("kind")
        if kind is not None and kind not in SECTION_KINDS:
            errs.append(
                f"sections[{i}]: kind '{kind}' は未対応。"
                f"{SECTION_KINDS} のいずれかにする"
            )

        for key in ("questions", "minutes"):
            val = sec.get(key)
            if val is not None and (not isinstance(val, int) or val < 1):
                errs.append(
                    f"sections[{i}]: {key} は 1 以上の整数にする（現在: {val!r}）"
                )

        n = sec.get("questions")
        quota = sec.get("domains")
        if quota is None:
            # domains 省略 = 全ドメイン横断（domains[].per_exam をそのまま使う）
            if isinstance(n, int) and n != global_total:
                errs.append(
                    f"sections[{i}] '{slug}': domains を省略しているので questions は "
                    f"per_exam 合計の {global_total} でなければならない（現在: {n}）"
                )
            continue

        if not isinstance(quota, dict) or not quota:
            errs.append(f"sections[{i}] '{slug}': domains が非空のマッピングではない")
            continue

        unknown = sorted(set(quota) - domain_ids)
        if unknown:
            errs.append(
                f"sections[{i}] '{slug}': 未知の domain id {unknown}"
                f"（domains に定義されているのは {sorted(domain_ids)}）"
            )
        sec_total = 0
        for did, v in quota.items():
            if not isinstance(v, int) or v < 0:
                errs.append(
                    f"sections[{i}] '{slug}': domains.{did} は 0 以上の整数にする"
                    f"（現在: {v!r}）"
                )
            else:
                sec_total += v
        if isinstance(n, int) and sec_total != n:
            errs.append(
                f"sections[{i}] '{slug}': domains の合計 {sec_total} が "
                f"questions {n} と一致しない"
            )

    return errs


def forbidden_sources(profile: dict) -> dict[str, str]:
    """出典に使ってはいけないホストと、その理由。

    front matter の任意キー `forbidden_sources`（`host` と `reason` を持つ要素の配列）
    から読む。指定がなければ空。資格ごとに事情が違う（製品ページで本文を含まない、
    旧ホストで転送される、など）ので harness 側にハードコードしない。
    """
    out: dict[str, str] = {}
    for item in profile.get("forbidden_sources") or []:
        if isinstance(item, dict) and item.get("host"):
            out[str(item["host"]).strip()] = str(item.get("reason", "")).strip()
        elif isinstance(item, str):
            out[item.strip()] = ""
    return out


def source_titles(profile: dict) -> dict[str, str]:
    """ホスト名 → sources.md に出す表示名。任意キー `source_titles`（辞書）から読む。"""
    raw = profile.get("source_titles") or {}
    if not isinstance(raw, dict):
        return {}
    return {str(k).strip(): str(v).strip() for k, v in raw.items()}


def guide_citation(profile: dict) -> str:
    """Exam Guide だけが根拠の事実に使う出典表記。

    任意キー `guide_citation` を優先し、無ければ `exam_code`（無ければ `cert`）から
    組み立てる。`check_sources.py` が「URL は無いが出典はある」行を認めるために使う。
    """
    explicit = profile.get("guide_citation")
    if explicit:
        return str(explicit).strip()
    code = profile.get("exam_code") or profile.get("cert") or ""
    return f"公式 Exam Guide（{code}）".strip()


def domain_quota(profile: dict, section=None) -> dict[str, int]:
    """ドメイン別の出題ノルマ。

    section を渡すと**そのセクションの**ノルマを返す（mixed モードでは本ごとに
    配分が違う）。section を渡さない場合・解決できない場合は
    domains[].per_exam をそのまま返すので、既存の呼び出しは挙動が変わらない。
    """
    globally = {d["id"]: d["per_exam"] for d in profile["domains"]}
    if section is None:
        return globally
    spec = resolve_section(profile, section)
    if spec is None:
        return globally
    return spec["quota"]


def section_specs(profile: dict) -> list:
    """本ごとの仕様を正規化して返す。

    **mock-exam モードも mixed の特殊ケースとして同じ形で返す**ので、
    呼び出し側は mode を気にしなくてよい。キーは
    slug / title / kind / questions / minutes / quota。
    """
    globally = {d["id"]: d["per_exam"] for d in profile["domains"]}
    if profile.get("mode") != "mixed":
        n = profile["mock_exams"]
        qpe = profile["questions_per_exam"]
        minutes = (profile.get("exam") or {}).get("minutes")
        return [
            {
                "slug": f"section{i:02d}-mock-exam-{i}",
                "title": f"模擬試験 第{i}回",
                "kind": "mock",
                "questions": qpe,
                "minutes": minutes,
                "quota": dict(globally),
            }
            for i in range(1, n + 1)
        ]

    specs = []
    for sec in profile["sections"]:
        quota = sec.get("domains")
        specs.append(
            {
                "slug": sec["slug"],
                "title": sec["title"],
                "kind": sec["kind"],
                "questions": sec["questions"],
                "minutes": sec["minutes"],
                "quota": dict(quota) if quota else dict(globally),
            }
        )
    return specs


def resolve_section(profile: dict, ref):
    """セクション参照を仕様に解決する。slug / フォルダ名 / パス / 1始まりの番号。

    スクリプトはセクションフォルダやその中の quiz.csv のパスを受け取るので、
    `section01-drill-1/quiz.csv` のようなパスからも引けるようにしておく。
    解決できなければ None を返す（呼び出し側は全体ノルマにフォールバックする）。
    """
    specs = section_specs(profile)
    if isinstance(ref, int):
        return specs[ref - 1] if 1 <= ref <= len(specs) else None

    text = str(ref).replace(chr(92), "/").rstrip("/")
    parts = [x for x in text.split("/") if x]
    by_slug = {x["slug"]: x for x in specs}
    # パスの末尾から順に見て slug と一致する要素を探す
    for part in reversed(parts):
        if part in by_slug:
            return by_slug[part]
    return None


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
    specs = section_specs(profile)
    total = sum(x["questions"] for x in specs)
    print(
        f"OK: {profile['cert']} / mode={profile['mode']} / "
        f"{len(specs)} sections / {total} questions"
    )
    for x in specs:
        print(
            f"  {x['slug']}  {x['kind']:<5} {x['questions']:>4}問 "
            f"{x['minutes']}分  quota={x['quota']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
