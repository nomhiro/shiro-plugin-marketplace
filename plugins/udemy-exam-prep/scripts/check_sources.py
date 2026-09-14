"""quiz.csv の出典を検査する。

有料講座でリンク切れ・無内容なリンクは実害があるため、各セクションの生成後に必ず通す。

検査項目:
  1. 全問に出典があるか（URL または Exam Guide 参照）
  2. 出典に使ってはいけないホストが混ざっていないか
     禁止ホストは `sections.md` front matter の任意キー `forbidden_sources` で指定する。
     典型例は「受験申込の製品ページで本文を含まない」「旧ホストで 301/302 転送される」。
  3. URL が実際に HTTP 200 を返すか（`--check-urls` 指定時のみ。ネットワークアクセスあり）

使い方:
    python check_sources.py section01-mock-exam-1/quiz.csv
    python check_sources.py section0*/quiz.csv --check-urls
    python check_sources.py section0*/quiz.csv --sections sections.md
"""
from __future__ import annotations

import argparse
import re
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path

# 直接実行（python .../scripts/x.py）でも兄弟モジュールを解決できるようにする。
# pytest からは scripts パッケージとして import されるため、その場合は何もしない。
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


from scripts.validate_quiz_csv import read_rows  # noqa: E402
from scripts._console import safe_stdout  # noqa: E402
from scripts.profile import (  # noqa: E402
    ProfileError, forbidden_sources, guide_citation, load_profile,
)

# 末尾の句読点・閉じ括弧は URL に含めない
URL_RE = re.compile(r"https?://[^\s)）、。，」』】>]+")
# Exam Guide 参照の既定パターン（front matter の guide_citation があればそれを使う）
DEFAULT_GUIDE_RE = re.compile(r"Exam\s*Guide")

UA = "Mozilla/5.0 (compatible; udemy-exam-prep-source-check/1.0)"


def load_policy(sections_md) -> tuple[dict[str, str], re.Pattern]:
    """禁止ホストと Exam Guide 参照パターンを front matter から読む。

    sections.md が無い・読めない場合は「禁止ホストなし・既定パターン」で続行する
    （出典欠落の検査だけは常に効かせたいため、ここで止めない）。
    """
    try:
        profile = load_profile(sections_md)
    except (ProfileError, FileNotFoundError, OSError):
        return {}, DEFAULT_GUIDE_RE
    cite = guide_citation(profile)
    # 「公式 Exam Guide（CODE）」のうち、記号を含まない語だけを緩く拾う
    words = [re.escape(w) for w in re.findall(r"[^\s（）()]+", cite)][:2]
    pat = re.compile(r"\s*".join(words)) if words else DEFAULT_GUIDE_RE
    return forbidden_sources(profile), pat


def extract_urls(cell: str) -> list[str]:
    return [u.rstrip(".,") for u in URL_RE.findall(cell)]


def http_status(url: str, timeout: float = 20.0) -> int:
    """200 を期待。到達できなければ 0 を返す。"""
    req = urllib.request.Request(url, headers={"User-Agent": UA}, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:
        return 0


def check(path: Path, check_urls: bool,
          forbidden: dict[str, str] | None = None,
          guide_re: re.Pattern | None = None) -> tuple[list[str], Counter, set[str]]:
    forbidden = forbidden or {}
    guide_re = guide_re or DEFAULT_GUIDE_RE
    errors: list[str] = []
    hosts: Counter[str] = Counter()
    urls: set[str] = set()

    rows = read_rows(path)
    for i, row in enumerate(rows[1:], 1):
        if len(row) != 17:
            errors.append(f"Q{i}: 17カラムではない")
            continue
        overall = row[15]
        found = extract_urls(overall)
        has_guide = bool(guide_re.search(overall))

        if not found and not has_guide:
            errors.append(f"Q{i}: 出典がない（URL も Exam Guide 参照もない）")

        for u in found:
            host = re.match(r"https?://([^/]+)", u).group(1)
            hosts[host] += 1
            urls.add(u)
            for bad, why in forbidden.items():
                if host == bad or host.endswith("." + bad):
                    tail = f" - {why}" if why else ""
                    errors.append(f"Q{i}: 出典に {bad} を使っている{tail}")

    if check_urls:
        for u in sorted(urls):
            code = http_status(u)
            if code != 200:
                errors.append(f"URL が 200 を返さない [{code}]: {u}")
            time.sleep(1.5)          # レート制限を避ける

    return errors, hosts, urls


def main(argv: list[str]) -> int:
    safe_stdout()
    ap = argparse.ArgumentParser(description="quiz.csv の出典を検査する")
    ap.add_argument("csv_paths", nargs="+")
    ap.add_argument("--sections", default="sections.md",
                    help="禁止ホストと Exam Guide 参照パターンの取得元")
    ap.add_argument(
        "--check-urls", action="store_true",
        help="URL に実際にアクセスして 200 を確認する（ネットワークアクセスあり・1.5秒間隔）",
    )
    a = ap.parse_args(argv[1:])

    forbidden, guide_re = load_policy(a.sections)

    failed = False
    for target in a.csv_paths:
        path = Path(target)
        errors, hosts, urls = check(path, a.check_urls, forbidden, guide_re)
        n = len(read_rows(path)) - 1
        if errors:
            failed = True
            print(f"FAIL {target}: {len(errors)} 件")
            for e in errors[:25]:
                print(f"  - {e}")
            if len(errors) > 25:
                print(f"  ... 他 {len(errors) - 25} 件")
        else:
            checked = "・URL 到達確認済み" if a.check_urls else ""
            print(f"OK   {target}: {n} 問すべてに適正な出典{checked}")
        print(f"       ホスト別: {dict(hosts)} / ユニークURL {len(urls)} 件")

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
