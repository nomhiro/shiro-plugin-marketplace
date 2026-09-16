---
name: quiz-csv-format
description: Udemy Practice Test Bulk Upload Template の17カラムCSV形式の規約、multi-select の正解数ルール、BOM・エスケープ・検証スクリプトを定義。quiz.csv を書く/編集するすべてのスキルとエージェントが従う。
---

# quiz-csv-format

`quiz.csv` は Udemy の **Practice Test Bulk Upload Template v2** に準拠する必要がある。1行でも形式逸脱があるとアップロードが全件失敗する。

## 17カラムの仕様

| 列 | 名前 | 必須 | 内容 |
|---|------|------|------|
| 1 | Question | 必須 | 問題文。言語は `sections.md` front matter の `exam.language` に従う。セル内改行は避け1行で書く |
| 2 | Question Type | 必須 | `multiple-choice` または `multi-select` のみ |
| 3 | Answer Option 1 | 必須 | 選択肢1のテキスト |
| 4 | Explanation 1 | 必須 | 選択肢1の解説 |
| 5 | Answer Option 2 | 必須 | 選択肢2のテキスト |
| 6 | Explanation 2 | 必須 | 選択肢2の解説 |
| 7 | Answer Option 3 | 必須 | 選択肢3のテキスト |
| 8 | Explanation 3 | 必須 | 選択肢3の解説 |
| 9 | Answer Option 4 | 必須 | 選択肢4のテキスト |
| 10 | Explanation 4 | 必須 | 選択肢4の解説 |
| 11 | Answer Option 5 | 任意 | 選択肢5のテキスト（無ければ空） |
| 12 | Explanation 5 | 任意 | 選択肢5の解説（無ければ空） |
| 13 | Answer Option 6 | 任意 | 選択肢6のテキスト（無ければ空） |
| 14 | Explanation 6 | 任意 | 選択肢6の解説（無ければ空） |
| 15 | Correct Answers | 必須 | 正解番号。`multiple-choice` は `3` のように1個。`multi-select` は `1,3,5` のようにカンマ区切り |
| 16 | Overall Explanation | 必須 | 正解の理由 + 具体例 + 出典URL |
| 17 | Domain | 必須 | `sections.md` front matter の `domains[].name` の値を**そのまま**書く（`D1` のような ID ではない）。セクション番号は含めない |

## CSV ヘッダー

```csv
Question,Question Type,Answer Option 1,Explanation 1,Answer Option 2,Explanation 2,Answer Option 3,Explanation 3,Answer Option 4,Explanation 4,Answer Option 5,Explanation 5,Answer Option 6,Explanation 6,Correct Answers,Overall Explanation,Domain
```

## 厳守ルール

1. **全行が正確に17カラム** — 選択肢が4〜5個でも空ペアで17カラムに揃える
2. **選択肢と解説はペアで揃える** — 選択肢が空なら解説も空。片方だけ埋めるのは不可
3. **multi-select の正解は2個以上、かつ誤答（distractor）を最低1つ持つ** — 正解が1個しかなければ `multiple-choice` に変更する（Udemy 側でアップロード時にエラー）。**全選択肢が正解（`正解数 = 選択肢数`）は不可** — 「全部選べばよい」問題になり品質欠陥。`正解数 < 選択肢数` を満たすこと
4. **正解番号は存在する選択肢の範囲内** — 選択肢4個なのに `5` を指すのは不可
5. **BOM を含めない** — `utf-8` で保存（`utf-8-sig` で書くと Udemy がヘッダー不正と判定する）
6. **改行を含むセルは `"` で囲む / ダブルクォートは `""` にエスケープ** — Python の `csv.writer` を使えば自動処理される
7. **日本語カンマ `、` は問題ない** — 半角カンマがセル内に含まれる場合のみクォート必要
8. **セル内に改行を書かない** — csv としては正しく引用されるので他の検査は通るが、Udemy の一括取り込みで破損要因になる。1セル1行で書く
9. **`<単語>` 形の文字列を書かない** — `<role>` `<context>` `</example>` `<br/>` のような形は **Udemy のサニタイザが HTML タグと判定して中身ごと削除する**。XML タグに言及したいときは**括弧を外して名前だけ書く**

```
NG  Wrap the request in <role>, <context>, and <output> tags
OK  Wrap the request in role, context, and output XML tags
NG  <role>、<context>、<output>タグでその依頼を包む
OK  role、context、outputのXMLタグでその依頼を包む
```

> 実績: 上の NG がそのまま投入され、Udemy 上で
> `Wrap the request in , , and tags` になった。**選択肢の意味が消えて解けない問題になり、
> 一括アップロードは成功アラートを出したので投入時には気づけなかった。**
> CSV の中身は完全に正しいため、列数・正解番号・改行・文体のどの検査も通っていた。
> `a < b` や `->` のような比較・矢印は対象外（検査は `<単語>` 形だけに当たる）。

## 必須検証

> 検証ロジックは `scripts/validate_quiz_csv.py` が**唯一の定義元**。
> [[upload-practice-tests]] / [[udemy-bulk-upload]] / [[exam-validator]] はこれを呼び、独自の簡易版を持たない。

`quiz.csv` を書いた直後、必ず実行する。

```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/validate_quiz_csv.py" <quiz.csv> [<quiz.csv> ...]
```

出力例:

```
OK   section01-mock-exam-1/quiz.csv: 60 questions, all valid
```

FAIL の場合は違反行と理由が列挙される。exit code は妥当なら 0、違反があれば 1。

検証項目:

1. BOM が無い
2. ヘッダーが17カラムかつ文字列一致
3. 全データ行が17カラム
4. `Question Type` が `multiple-choice` / `multi-select`
5. `multiple-choice` の正解はちょうど1個
6. `multi-select` の正解は2個以上
7. 正解番号が整数かつ存在する選択肢の範囲内
8. `multi-select` は誤答を最低1つ持つ
9. 必須列が空でない
10. 選択肢と解説がペアで揃っている

## 安全な入出力パターン

**CSV の読み書きはスクリプトの関数を使う。** 自前で `open()` しない。

```python
import sys
sys.path.insert(0, "<CLAUDE_PLUGIN_ROOT>")
from scripts.validate_quiz_csv import HEADER, read_rows, write_rows

rows = [list(HEADER)] + data_rows   # data_rows は各要素が17要素のリスト
write_rows("section01-mock-exam-1/quiz.csv", rows)   # utf-8 / BOM無し / newline='' / QUOTE_MINIMAL

back = read_rows("section01-mock-exam-1/quiz.csv")   # utf-8-sig で読む（BOM があっても透過）
```

**注意:**
- 書き出しは必ず `encoding='utf-8'`（**`utf-8-sig` 禁止**）
- 読み込みは `encoding='utf-8-sig'`（既存ファイルに BOM が混じっていても透過処理）
- `newline=''` を指定しないと Windows で空行が入る
- 大量の行を書くときは Bash heredoc を使わない（クォートエスケープ事故が起きやすい）

## ペアになるスキル・エージェント

- 解説の品質とスタイルは [[question-author]] を参照（解説スタイルは question-author に内包）
- 選択肢の位置バイアス除去は `scripts/shuffle_options.py`（[[create-section]] が呼ぶ）
