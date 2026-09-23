"""quiz.csv の出典を検査する。

有料講座でリンク切れ・無内容なリンクは実害があるため、各セクションの生成後に必ず通す。

検査項目:
  1. 全問に出典があるか（URL または Exam Guide 参照）
  2. 出典に使ってはいけないホストが混ざっていないか
     禁止ホストは `sections.md` front matter の任意キー `forbidden_sources` で指定する。
     典型例は「受験申込の製品ページで本文を含まない」「旧ホストで 301/302 転送される」。
  3. URL が実際に HTTP 200 を返すか（`--check-urls` 指定時のみ。ネットワークアクセスあり）
  4. 出典 URL が問題のドメインに対応するドキュメント領域か
     front matter の任意キー `source_scope` でドメインごとに許可する URL 接頭辞を
     定義した場合だけ検査する。範囲外は既定で WARN、`severity: fail` で FAIL。
     ホストが同じでも製品（ドキュメント領域）が違うページを出典にした問題は、
     1-3 の検査をすべて通る（実績: ある講座で、ある製品の問題の出典が
     同じホストの別製品のページになっている問題が2件、精読レビューまで残った）。

使い方:
    python check_sources.py section01-mock-exam-1/quiz.csv
    python check_sources.py section0*/quiz.csv --check-urls
    python check_sources.py section0*/quiz.csv --sections sections.md
    python check_sources.py section0*/quiz.csv --sections sections.md --scope-strict

`source_scope` の書き方（sections.md front matter）:

    source_scope:
      severity: warn                  # warn（既定）| fail
      include_primary_sources: true   # primary_sources[].scope / url 中の URL を全ドメイン共通で許可
      common:                         # 全ドメイン共通で許可する接頭辞
        - docs.example.com/product-a/
      domains:                        # ドメイン id ごとに追加で許可する接頭辞
        D4:
          - docs.example.com/identity/

接頭辞は `ホスト/パス`（スキーム省略可）。ロケールセグメント（/en-us/ など）は
normalize_urls.py がロケール規則を持つホストに限り比較前に取り除くので、
書いても書かなくてもよい。パスはセグメント単位で比較する
（`product-a` は `product-ab` に一致しない）。
許可リストが空のドメイン（common も domains.<id> も無い）は検査しない。
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


from scripts.validate_quiz_csv import SOURCE_RE, read_rows  # noqa: E402
from scripts._console import safe_stdout  # noqa: E402
from scripts.profile import (  # noqa: E402
    ProfileError, forbidden_sources, guide_citation, load_profile,
)
from scripts.normalize_urls import LOCALE_RULES  # noqa: E402

# 末尾の句読点・閉じ括弧は URL に含めない
# 日本語・全角文字で停止させる。停止させないと
# `出典: https://example.com/page【設問の訳】…` のような詰め書きで
# URL が訳文を飲み込み、--check-urls が 404 で落ちる（実績: ある講座で27箇所）。
# 旧版は 】 だけを除外し 【 を含めていなかったため、ここを取り逃がしていた。
URL_RE = re.compile(r"https?://[^\s\u3000-\u9fff\uff00-\uffef)）、。，」』【】>]+")
# Exam Guide 参照の既定パターン（front matter の guide_citation があればそれを使う）
DEFAULT_GUIDE_RE = re.compile(r"Exam\s*Guide")

UA = "Mozilla/5.0 (compatible; udemy-exam-prep-source-check/1.0)"


def guide_pattern(profile: dict) -> re.Pattern:
    """「URL は無いが出典はある」と認める表記のパターンを front matter から作る。

    **決め打ちの文字列で探してはいけない。** `guide_citation` は資格ごとに違う
    （`公式 Exam Guide（CODE）` / `JDLA 公式シラバス（…）` など）。
    決め打ちにすると、別表記の資格でシラバス引用の問題が丸ごと
    「出典がない」と誤検出される（実績: ある講座で約100件）。

    audit_course.py もこれを使う（同じ規則を2箇所に持たせない）。
    """
    cite = guide_citation(profile)
    # 「公式 Exam Guide（CODE）」のうち、記号を含まない語だけを緩く拾う
    words = [re.escape(w) for w in re.findall(r"[^\s（）()]+", cite)][:2]
    return re.compile(r"\s*".join(words)) if words else DEFAULT_GUIDE_RE


def load_policy(sections_md) -> tuple[dict[str, str], re.Pattern]:
    """禁止ホストと Exam Guide 参照パターンを front matter から読む。

    sections.md が無い・読めない場合は「禁止ホストなし・既定パターン」で続行する
    （出典欠落の検査だけは常に効かせたいため、ここで止めない）。
    """
    try:
        profile = load_profile(sections_md)
    except (ProfileError, FileNotFoundError, OSError):
        return {}, DEFAULT_GUIDE_RE
    return forbidden_sources(profile), guide_pattern(profile)


def extract_urls(cell: str) -> list[str]:
    return [u.rstrip(".,") for u in URL_RE.findall(cell)]


# --- 出典のドキュメント領域（source_scope） ---------------------------------

SCOPE_SEVERITIES = ("warn", "fail")
_LOCALE_RE = re.compile(r"^(?:[a-z]{2}-[a-z]{2}|[a-z]{2})$", re.I)


def _norm_domain_name(name) -> str:
    """Domain 列の比較用。空白の有無の揺れ（全角・半角を含む）を吸収する。"""
    return re.sub(r"\s+", "", str(name))


def url_key(url: str) -> tuple[str, list[str]]:
    """URL を (ホスト, パスセグメント列) に正規化する。

    スキーム・クエリ・フラグメントを落とし、normalize_urls.py がロケール規則を
    持つホストに限って第1セグメントのロケールを取り除く。ロケール規則の無い
    ホストで2文字のセグメントを消すと別ページを指してしまうので、ホストを限定する。
    check_sources は normalize_urls より前に走るため、quiz 側も front matter 側も
    ロケールの有無がばらばらでよいようにしておく。
    """
    text = re.sub(r"^[a-z][a-z0-9+.-]*://", "", url.strip(), flags=re.I)
    text = re.split(r"[?#]", text, maxsplit=1)[0]
    host, _, path = text.partition("/")
    host = host.lower()
    segs = [x for x in path.split("/") if x]
    if segs and LOCALE_RULES.get(host) and _LOCALE_RE.match(segs[0]):
        segs = segs[1:]
    return host, [x.lower() for x in segs]


def in_prefix(url: str, prefix: str) -> bool:
    """url が prefix の配下か（ホスト一致 + パスのセグメント単位の前方一致）。"""
    h, segs = url_key(url)
    ph, psegs = url_key(prefix)
    return h == ph and segs[: len(psegs)] == psegs


def load_scope(profile: dict) -> tuple[dict | None, list[str]]:
    """front matter の `source_scope` を正規化する。(scope, 設定エラー) を返す。

    scope は {"severity", "common": [...], "domains": {id: [...]}, "names": {正規化名: id}}。
    `source_scope` が無ければ (None, [])。

    設定の誤り（未知のドメイン id・リストでない値）は severity に関係なく
    エラーとして返す。黙って無視すると、打ち間違い1つで検査が止まったことに
    誰も気づかない。
    """
    raw = profile.get("source_scope")
    if raw is None:
        return None, []
    if not isinstance(raw, dict):
        return None, ["source_scope がマッピングではない"]
    errs: list[str] = []

    severity = str(raw.get("severity") or "warn").strip().lower()
    if severity not in SCOPE_SEVERITIES:
        errs.append(
            f"source_scope.severity '{severity}' は {SCOPE_SEVERITIES} のいずれかにする"
        )
        severity = "warn"

    def as_list(val, where) -> list[str]:
        if val is None:
            return []
        if isinstance(val, str):
            return [val.strip()] if val.strip() else []
        if not isinstance(val, list):
            errs.append(f"{where} がリストではない")
            return []
        return [str(x).strip() for x in val if str(x).strip()]

    common = as_list(raw.get("common"), "source_scope.common")
    if raw.get("include_primary_sources"):
        # primary_sources[].scope は自由記述（ローカルファイル名や説明文を含む）
        # なので、URL の形をしたものだけを拾う
        for src in profile.get("primary_sources") or []:
            if isinstance(src, dict):
                texts = [str(src.get(k) or "") for k in ("url", "scope")]
            else:
                texts = [str(src)]
            for t in texts:
                common.extend(extract_urls(t))

    domain_ids: dict[str, str] = {}
    for d in profile.get("domains") or []:
        if isinstance(d, dict) and d.get("id") is not None:
            domain_ids[str(d["id"])] = str(d.get("name", ""))

    per_domain: dict[str, list[str]] = {}
    doms = raw.get("domains") or {}
    if not isinstance(doms, dict):
        errs.append("source_scope.domains がマッピングではない")
        doms = {}
    for did, val in doms.items():
        if str(did) not in domain_ids:
            errs.append(
                f"source_scope.domains に未知のドメイン id '{did}'"
                f"（domains に定義されているのは {sorted(domain_ids)}）"
            )
            continue
        per_domain[str(did)] = as_list(val, f"source_scope.domains.{did}")

    # Domain 列には正式名が入る。id を直接書いた行も引けるようにしておく
    names = {_norm_domain_name(n): i for i, n in domain_ids.items()}
    names.update({_norm_domain_name(i): i for i in domain_ids})
    scope = {"severity": severity, "common": common,
             "domains": per_domain, "names": names}
    return scope, errs


def source_part(overall: str) -> str:
    """Overall Explanation の出典部分（`出典:` 以降）。目印が無ければ全体。

    本文中のコードや OAuth スコープ（`https://<resource>/.default` など）は
    出典ではないので、出典の目印があるときは目印以降だけを見る。
    """
    m = SOURCE_RE.search(overall)
    return overall[m.start():] if m else overall


def check_scope(rows: list[list[str]], scope: dict) -> list[str]:
    """各問の出典 URL が、その問題のドメインで許可された接頭辞の配下かを見る。

    Domain 列が未知の値の行は飛ばす（validate_exam.py が FAIL にするので二重に出さない）。
    許可リストが空のドメインは検査しない。
    """
    out: list[str] = []
    for i, row in enumerate(rows[1:], 1):
        if len(row) != 17:
            continue
        did = scope["names"].get(_norm_domain_name(row[16]))
        if did is None:
            continue
        allowed = scope["common"] + scope["domains"].get(did, [])
        if not allowed:
            continue
        for u in dict.fromkeys(extract_urls(source_part(row[15]))):
            if not any(in_prefix(u, p) for p in allowed):
                out.append(f"Q{i} [{did}]: 出典がドメインの source_scope 外: {u}")
    return out


def load_scope_file(sections_md) -> tuple[dict | None, list[str]]:
    """sections.md から source_scope を読む。読めなければ検査しない。"""
    try:
        return load_scope(load_profile(sections_md))
    except (ProfileError, FileNotFoundError, OSError):
        return None, []


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
    ap.add_argument(
        "--scope-strict", action="store_true",
        help="source_scope 外の出典を severity に関係なく FAIL にする",
    )
    a = ap.parse_args(argv[1:])

    forbidden, guide_re = load_policy(a.sections)
    scope, scope_errs = load_scope_file(a.sections)
    if scope_errs:
        print(f"FAIL {a.sections}: source_scope の設定が不正（{len(scope_errs)} 件）")
        for e in scope_errs:
            print(f"  - {e}")
    scope_fail = bool(scope) and (a.scope_strict or scope["severity"] == "fail")

    failed = False
    for target in a.csv_paths:
        path = Path(target)
        errors, hosts, urls = check(path, a.check_urls, forbidden, guide_re)
        out_of_scope = check_scope(read_rows(path), scope) if scope else []
        if scope_fail:
            errors += out_of_scope
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
        if out_of_scope and not scope_fail:
            print(f"WARN {target}: 出典がドメインの source_scope 外 {len(out_of_scope)} 件"
                  "（別製品のページを出典にしていないか、正答が出典と食い違って"
                  "いないかを1問ずつ確認する）")
            for e in out_of_scope[:25]:
                print(f"  - {e}")
            if len(out_of_scope) > 25:
                print(f"  ... 他 {len(out_of_scope) - 25} 件")

    return 1 if failed or scope_errs else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
