"""ドメイン別のパート CSV を1本のフル模試 quiz.csv に結合する。

question-author を D1〜D5 で並列に走らせると、同じ quiz.csv への同時書き込みで
競合する。そこで各エージェントには `_parts/<domain-id>.csv` と
`_parts/<domain-id>-meta.tsv` だけを書かせ、結合はこのスクリプトが決定的に行う。

- 結合順は sections.md の front matter の domains の順（D1, D2, ... ）
- 通し番号（Q1..QN）はここで振る
- question-bank.md に追記する行もここで生成する（exam-validator が使う）

**question-bank の問題文は meta ではなく CSV から取る。** 長さバイアスの是正や
創作識別子のリネームで CSV を外科的に直すと meta の `head` だけが古くなり、
重複管理のインデックスが実物と食い違う（実績: ある講座で5本13ファイルが古くなった）。
CSV を正とし、meta が食い違ったら報告する。**meta の head が別の行の問題文に
一致する場合は行のずれ**で、`tested_concept` が別の問題に紐づく致命的な破損なので
FAIL にする。

**日本語と英数字の間の半角スペースの有無が割れていたら警告する。** 作問を
分割すると回ごとに癖が割れる（実績: ある講座の1本で Q1-25 はスペース無し、
Q26-50 はあり）。1パートの中で割れることもあるので、行ごとに判定して
少数派の行範囲をパート別に報告する。`--normalize` で多数派に揃える
（URL・バッククォート内・Domain 列は触らない。URL 直後の半角スペースは
`check_style` の規則で必須なので消さない）。揃えた内容はパート CSV にも
書き戻す（書き戻さないと次の結合で割れが戻る）。

**結合し直すと消える手直しがあれば止める。** 結合は quiz.csv を上書きする。
quiz.csv や quiz.raw.csv を直接直していた場合、その修正は `_parts` に無いので
消える。原本（quiz.raw.csv）との三者比較でそれを検出し、`--force` が無ければ
上書きしない。

使い方:
    python tools/merge_parts.py section01-mock-exam-1
    python tools/merge_parts.py section01-mock-exam-1 --keep-parts
    python tools/merge_parts.py section01-mock-exam-1 --keep-parts --normalize
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# 直接実行（python .../scripts/x.py）でも兄弟モジュールを解決できるようにする。
# pytest からは scripts パッケージとして import されるため、その場合は何もしない。
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


from scripts._console import safe_stdout  # noqa: E402
from scripts.check_style import URL_RE  # noqa: E402
from scripts.normalize_urls import normalize_text  # noqa: E402
from scripts.profile import domain_names, domain_quota, load_profile  # noqa: E402
from scripts.shuffle_options import row_fingerprint  # noqa: E402
from scripts.validate_quiz_csv import (  # noqa: E402
    HEADER, read_rows, validate_csv, write_rows,
)

META_FIELDS = ("local_no", "domain", "task_statement", "tested_concept", "scenario", "head")

# --- 日本語と英数字の間の半角スペース -----------------------------------------
# 日本語はかな・漢字だけ（句読点・括弧・中黒は境界に数えない）
_JA = "\u3040-\u30fa\u30fc-\u30ff\u3400-\u4dbf\u4e00-\u9fff"
_AN = "A-Za-z0-9"
GLUED_RE = re.compile(f"(?<=[{_JA}])(?=[{_AN}])|(?<=[{_AN}])(?=[{_JA}])")
SPACED_RE = re.compile(f"(?<=[{_JA}]) (?=[{_AN}])|(?<=[{_AN}]) (?=[{_JA}])")
# 触らない区間: バッククォート内と URL（URL の直後の空白は区間の外だが、
# 区間の端に接する文字は置換の対象にならないので消えない）
PROTECT_RE = re.compile(f"`[^`\n]*`|{URL_RE.pattern}")
# 走査するカラム（Question Type / Correct Answers / Domain は除く）
SPACING_COLS = tuple(c for c in range(16) if c not in (1, 14))
# 1行の判定に必要な境界の数（これ未満の行は判定しない）
MIN_BOUNDARIES = 3
# 少数派がこの行数以上なら警告する
MIN_MINORITY_ROWS = 3


def read_meta(path: Path) -> list[dict]:
    """meta.tsv を読む。

    ヘッダー行は「なし」が仕様だが、エージェントが付けてくることがある
    （実績: 3本目の D2）。1列目が連番でない行はヘッダーとみなして捨てる。
    """
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if not line.strip():
            continue
        cells = line.split("\t")
        if len(cells) < len(META_FIELDS):
            raise SystemExit(
                f"{path}: タブ区切りの列が {len(cells)} 個しかない"
                f"（{len(META_FIELDS)} 個必要）: {line[:80]}"
            )
        if not cells[0].strip().isdigit():
            continue                       # ヘッダー行
        rows.append(dict(zip(META_FIELDS, [c.strip() for c in cells])))
    return rows


def _norm_head(text: str) -> str:
    """head の比較用に正規化する。

    エージェントは冒頭何字かを手で写すため、空白の入り方・大文字小文字・
    末尾の省略記号が揺れる。揺れで誤検出しないところまで落とす。
    """
    t = re.sub(r"\s+", "", text).lower().replace("|", "/")
    return t.rstrip(".…。")


def head_mismatches(body: list[list[str]], meta: list[dict]) -> tuple[list[str], list[str]]:
    """meta の head と CSV の問題文を突き合わせる。

    戻り値は (行のずれ, 古いだけ)。ずれは FAIL、古いだけなら CSV を採用して WARN。
    """
    csv_heads = [_norm_head(r[0]) for r in body]
    misaligned: list[str] = []
    stale: list[str] = []
    for i, m in enumerate(meta, 1):
        want = _norm_head(m.get("head") or "")
        if not want or csv_heads[i - 1].startswith(want):
            continue
        j = next((k + 1 for k, h in enumerate(csv_heads) if h.startswith(want)), None)
        if j is not None:
            misaligned.append(
                f"meta {i} 行目の head が CSV {j} 行目の問題文に一致する"
                "（行がずれている。tested_concept が別の問題に紐づく）"
            )
        else:
            stale.append(
                f"meta {i} 行目の head が CSV の問題文と一致しない"
                f"（CSV を採用: {body[i - 1][0][:40]}...）"
            )
    return misaligned, stale


def _pieces(text: str):
    """(保護区間か, 文字列) の列に分ける。"""
    pos = 0
    for m in PROTECT_RE.finditer(text):
        if m.start() > pos:
            yield False, text[pos:m.start()]
        yield True, m.group(0)
        pos = m.end()
    if pos < len(text):
        yield False, text[pos:]


def spacing_counts(row: list[str]) -> tuple[int, int]:
    """1行の (スペースありの境界数, スペース無しの境界数)。"""
    spaced = glued = 0
    for c in SPACING_COLS:
        if c >= len(row):
            continue
        for protected, piece in _pieces(row[c]):
            if protected:
                continue
            spaced += len(SPACED_RE.findall(piece))
            glued += len(GLUED_RE.findall(piece))
    return spaced, glued


def _lean(spaced: int, glued: int) -> str | None:
    if spaced + glued < MIN_BOUNDARIES or spaced == glued:
        return None
    return "spaced" if spaced > glued else "glued"


def _ranges(nums: list[int]) -> str:
    out, start, prev = [], None, None
    for n in sorted(nums):
        if start is None:
            start = prev = n
        elif n == prev + 1:
            prev = n
        else:
            out.append(f"Q{start}" if start == prev else f"Q{start}-Q{prev}")
            start = prev = n
    if start is not None:
        out.append(f"Q{start}" if start == prev else f"Q{start}-Q{prev}")
    return ", ".join(out)


def spacing_report(entries: list[tuple[str, int, list[str]]]) -> dict:
    """(パートID, 通し番号, 行) の列から、スペース有無の多数派と少数派の行を返す。

    多数派は境界の総数で決める。少数派の行が MIN_MINORITY_ROWS 以上なら
    `split` が True になる（呼び出し側が警告する）。
    """
    spaced_total = glued_total = 0
    leans: list[tuple[str, int, str | None]] = []
    for did, no, row in entries:
        s_, g_ = spacing_counts(row)
        spaced_total += s_
        glued_total += g_
        leans.append((did, no, _lean(s_, g_)))
    if spaced_total + glued_total == 0:
        return {"majority": None, "spaced": 0, "glued": 0, "minority": {}, "split": False}
    majority = "spaced" if spaced_total >= glued_total else "glued"
    minority: dict[str, list[int]] = {}
    for did, no, lean in leans:
        if lean and lean != majority:
            minority.setdefault(did, []).append(no)
    n_min = sum(len(v) for v in minority.values())
    return {
        "majority": majority, "spaced": spaced_total, "glued": glued_total,
        "minority": minority, "split": n_min >= MIN_MINORITY_ROWS,
    }


def format_spacing_warning(rep_: dict) -> list[str]:
    label = {"spaced": "スペースあり", "glued": "スペース無し"}
    maj = rep_["majority"]
    other = "glued" if maj == "spaced" else "spaced"
    lines = [
        f"日本語と英数字の間の半角スペースが割れています（多数派: {label[maj]} / "
        f"境界 あり {rep_['spaced']} 件・無し {rep_['glued']} 件）"
    ]
    for did, nums in rep_["minority"].items():
        lines.append(f"  {did}: {label[other]}の行 {_ranges(nums)}")
    lines.append("  --normalize で多数派に揃えられます（URL・バッククォート内・Domain 列は触りません）")
    return lines


def normalize_spacing(text: str, majority: str) -> tuple[str, int]:
    """保護区間の外だけ、日本語と英数字の間の空白を多数派に揃える。"""
    out, n = [], 0
    for protected, piece in _pieces(text):
        if protected:
            out.append(piece)
            continue
        if majority == "spaced":
            new, k = GLUED_RE.subn(" ", piece)
        else:
            new, k = SPACED_RE.subn("", piece)
        out.append(new)
        n += k
    return "".join(out), n


def normalize_row_spacing(row: list[str], majority: str) -> tuple[list[str], int]:
    out, n = list(row), 0
    for c in SPACING_COLS:
        if c < len(out):
            out[c], k = normalize_spacing(out[c], majority)
            n += k
    return out, n


# --- 結合で消える手直しの検出 -------------------------------------------------

def _norm_urls(row: list[str]) -> list[str]:
    """URL のロケール正規化を当てた行（結合後の工程で quiz.csv だけに当たるため）。"""
    return [normalize_text(c)[0] for c in row]


def _same(a: list[str], b: list[str]) -> bool:
    return row_fingerprint(_norm_urls(a)) == row_fingerprint(_norm_urls(b))


def unmerged_edits(section: Path, merged: list[list[str]], part_files: list[Path]) -> list[str]:
    """結合で上書きすると失われる手直しを列挙する（空なら安全）。

    原本（quiz.raw.csv）は「最後にシャッフルした時点の内容」なので、これを基準に
    三者比較する:

    - quiz.csv が原本と同じ行: 手直しなし（`_parts` 側の変更は正規の経路）
    - quiz.csv が原本と違い、結合結果とも違う行: quiz.csv の手直しが消える
    - quiz.csv が結合結果と同じで原本だけ違う行: 原本が後から直されていれば
      その修正が消える（原本が quiz.csv より新しいときだけ数える。`_parts` と
      quiz.csv に同じ修正を入れた場合は古い原本が残るだけで何も失われない）

    原本が無い（シャッフル前）ときは、quiz.csv が全パートより新しく、かつ
    結合結果と違う場合だけを手直しとみなす（パートを直して結合し直す通常の
    反復では quiz.csv の方が古い）。
    """
    quiz = section / "quiz.csv"
    raw = section / "quiz.raw.csv"
    if not quiz.is_file():
        return []
    cur = read_rows(quiz)
    out: list[str] = []

    def head(row):
        return (row[0] if row else "")[:40]

    if raw.is_file():
        base = read_rows(raw)
        raw_newer = raw.stat().st_mtime > quiz.stat().st_mtime
        if len(cur) != len(base):
            if len(cur) == len(merged) and all(_same(a, b) for a, b in zip(cur[1:], merged[1:])):
                return []
            return [
                f"quiz.csv（{len(cur) - 1} 問）が原本（{len(base) - 1} 問）と行数から違い、"
                "結合結果とも一致しません"
            ]
        for i, (a, b) in enumerate(zip(cur[1:], base[1:]), 2):
            if row_fingerprint(a) == row_fingerprint(b):
                continue
            n = merged[i - 1] if i - 1 < len(merged) else None
            if n is None or not _same(a, n):
                out.append(f"Row {i}: quiz.csv の手直しが _parts に無い（{head(a)}...）")
            elif raw_newer and not _same(b, n):
                out.append(f"Row {i}: quiz.raw.csv の手直しが _parts に無い（{head(b)}...）")
        return out

    newest_part = max((p.stat().st_mtime for p in part_files), default=0.0)
    if quiz.stat().st_mtime <= newest_part:
        return []
    if len(cur) != len(merged):
        out.append(f"quiz.csv（{len(cur) - 1} 問）が結合結果（{len(merged) - 1} 問）と違います")
    for i, (a, n) in enumerate(zip(cur[1:], merged[1:]), 2):
        if not _same(a, n):
            out.append(f"Row {i}: quiz.csv の手直しが _parts に無い（{head(a)}...）")
    return out


def merge(
    section: Path, profile: dict, keep_parts: bool,
    normalize: bool = False, force: bool = False,
) -> dict:
    parts_dir = section / "_parts"
    if not parts_dir.is_dir():
        raise SystemExit(f"{parts_dir} がない。先に各ドメインのパートを生成する")

    names = domain_names(profile)
    # mixed モードでは本ごとに配分が違うので、セクション名で引く。
    # mock-exam モードや未登録のフォルダ名では全体ノルマに落ちる。
    quota = domain_quota(profile, section.name)

    merged: list[list[str]] = [list(HEADER)]
    bank: list[str] = []
    per_domain: dict[str, int] = {}
    warnings: list[str] = []
    global_no = 0
    loaded: list[tuple[str, Path, list[list[str]], list[dict]]] = []

    for did in quota:                      # front matter の domains 順
        csv_path = parts_dir / f"{did}.csv"
        meta_path = parts_dir / f"{did}-meta.tsv"
        if not csv_path.is_file():
            raise SystemExit(f"{csv_path} がない")
        if not meta_path.is_file():
            raise SystemExit(f"{meta_path} がない")

        errors = validate_csv(csv_path)
        if errors:
            print(f"FAIL {csv_path}: {len(errors)} error(s)")
            for e in errors[:10]:
                print(f"  - {e}")
            raise SystemExit(1)

        body = read_rows(csv_path)[1:]
        meta = read_meta(meta_path)
        if len(body) != len(meta):
            raise SystemExit(
                f"{did}: CSV {len(body)} 行 と meta {len(meta)} 行が一致しない"
            )
        if len(body) != quota[did]:
            raise SystemExit(
                f"{did}: {len(body)} 問だがノルマは {quota[did]} 問"
            )

        misaligned, stale = head_mismatches(body, meta)
        if misaligned:
            print(f"FAIL {meta_path}: meta と CSV の行がずれている")
            for e in misaligned[:10]:
                print(f"  - {e}")
            raise SystemExit(1)
        for e in stale:
            print(f"WARN {meta_path}: {e}")
            warnings.append(f"{did}: {e}")

        want = names[did]
        for i, row in enumerate(body):
            if row[16].strip() != want:
                raise SystemExit(
                    f"{did} の {i + 1} 行目: Domain 列が '{row[16]}' "
                    f"（'{want}' でなければならない）"
                )

        loaded.append((did, csv_path, body, meta))

    # 結合し直すと消える手直しの検査。**何かを書く前に**、パートの実際の内容
    # （正規化前）で比べる。正規化でパートを書き戻した後に比べると、パートの
    # mtime が新しくなって手直しを見逃すうえ、止まったときにパートだけ変わる。
    quiz = section / "quiz.csv"
    as_is = [list(HEADER)] + [r for _, _, body, _ in loaded for r in body]
    lost = unmerged_edits(section, as_is, [p for _, p, _, _ in loaded])
    if lost and not force:
        print(
            f"FAIL {quiz}: 結合し直すと消える手直しが {len(lost)} 件あります。"
            "上書きせずに停止しました"
        )
        for e in lost[:20]:
            print(f"  - {e}")
        print(
            "  手直しを _parts/<ドメイン>.csv に反映してから結合し直すか、"
            "捨ててよければ --force を付けてください"
        )
        raise SystemExit(1)
    if lost:
        print(f"NOTE: --force。_parts に無い手直し {len(lost)} 件を上書きします")

    # 日本語と英数字の間の半角スペース（パート間・パート内の割れ）
    entries, no = [], 0
    for did, _, body, _ in loaded:
        for row in body:
            no += 1
            entries.append((did, no, row))
    spacing = spacing_report(entries)
    normalized = 0
    if normalize and spacing["majority"]:
        for k, (did, csv_path, body, meta) in enumerate(loaded):
            new_body, changed = [], 0
            for row in body:
                new_row, n = normalize_row_spacing(row, spacing["majority"])
                new_body.append(new_row)
                changed += n
            if changed:
                # パートにも書き戻す（書き戻さないと次の結合で割れが戻る）
                write_rows(csv_path, [list(HEADER)] + new_body)
                loaded[k] = (did, csv_path, new_body, meta)
                normalized += changed
        if normalized:
            print(
                f"NOTE: 日本語と英数字の間の半角スペースを多数派"
                f"（{'あり' if spacing['majority'] == 'spaced' else '無し'}）に"
                f" {normalized} 箇所揃えました"
            )
    elif spacing["split"]:
        for line in format_spacing_warning(spacing):
            print(f"WARN {line}")
        warnings.append("日本語と英数字の間の半角スペースが割れている")

    for did, _, body, meta in loaded:
        for row, m in zip(body, meta):
            global_no += 1
            merged.append(row)
            # CSV を正とする（meta の head は外科的修正に追随しない）
            head = row[0][:60].replace("|", "/")
            bank.append(
                f"| {section.name[:9]} | Q{global_no} | {did} | "
                f"{m['task_statement']} | {m['tested_concept'].replace('|', '/')} | "
                f"{m['scenario']} | {head} |"
            )
        per_domain[did] = len(body)

    quiz = section / "quiz.csv"
    write_rows(quiz, merged)

    errors = validate_csv(quiz)
    if errors:
        print(f"FAIL {quiz}: {len(errors)} error(s)")
        for e in errors[:10]:
            print(f"  - {e}")
        raise SystemExit(1)

    bank_out = section / "_parts" / "bank-rows.md"
    bank_out.write_text("\n".join(bank) + "\n", encoding="utf-8", newline="\n")

    if not keep_parts:
        for p in sorted(parts_dir.glob("*.csv")):
            p.unlink()
        for p in sorted(parts_dir.glob("*-meta.tsv")):
            p.unlink()

    return {"total": global_no, "per_domain": per_domain,
            "bank_rows": str(bank_out), "warnings": warnings,
            "spacing": spacing, "normalized": normalized}


def main(argv: list[str]) -> int:
    safe_stdout()
    ap = argparse.ArgumentParser(description="ドメイン別パートを quiz.csv に結合する")
    ap.add_argument("section", help="例: section01-mock-exam-1")
    ap.add_argument("--sections", default="sections.md")
    ap.add_argument(
        "--keep-parts", action="store_true",
        help="結合後もパートファイルを残す（既定は削除。bank-rows.md は常に残る）",
    )
    ap.add_argument(
        "--normalize", action="store_true",
        help="日本語と英数字の間の半角スペースが割れていたら多数派に揃える（パート CSV にも書き戻す）",
    )
    ap.add_argument(
        "--force", action="store_true",
        help="quiz.csv / quiz.raw.csv に _parts に無い手直しがあっても上書きする（手直しは失われる）",
    )
    a = ap.parse_args(argv[1:])

    profile = load_profile(a.sections)
    result = merge(Path(a.section), profile, a.keep_parts,
                   normalize=a.normalize, force=a.force)

    print(f"OK: {a.section}/quiz.csv に {result['total']} 問を結合")
    for did, n in result["per_domain"].items():
        print(f"  {did}: {n}")
    print(f"  question-bank 追記用の行: {result['bank_rows']}")
    stale = [w for w in result["warnings"] if "半角スペース" not in w]
    if stale:
        print(
            f"  WARN {len(stale)} 件: meta.tsv の head が CSV と食い違う。"
            "CSV を採用したが、同じ行の tested_concept も古い可能性がある"
        )
    if result["spacing"]["split"] and not result["normalized"]:
        print("  WARN: 日本語と英数字の間の半角スペースが割れている（上記。--normalize で揃う）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
