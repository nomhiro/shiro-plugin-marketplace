---
name: init-exam-course
description: 試験番号を引数に、新しい試験対策問題集プロジェクトをテンプレートから初期化する。CLAUDE.md / sections.md / question-bank.md / removed-questions.md / .gitignore / Udemy CSV 参考ファイルを展開し、試験仕様をプレースホルダ置換で埋める。既存ファイルは上書きしない。スラッシュコマンド `/udemy-exam-prep:init-exam-course CCA-F` または「CCA-F の講座プロジェクトを作って」で起動。
---

# init-exam-course

新しい試験対策問題集プロジェクトの **最初のエントリーポイント**。テンプレートを展開して payload（資格固有ファイル）の骨組みを作ります。

## 起動例

```
/udemy-exam-prep:init-exam-course CCA-F
/udemy-exam-prep:init-exam-course
CCA-F の講座プロジェクトを作って
新しい試験対策講座を始めたい
```

## 何をするか

`templates/exam-course/` を**カレントディレクトリ**に展開し、8個のプレースホルダを置換します。

| 生成されるファイル | 内容 |
|---|---|
| `CLAUDE.md` | プロジェクト方針・ワークフロー全体図・レビュー断面・クイズ作成ガイドライン |
| `sections.md` | 試験プロファイル（front matter）＋ブループリントの TODO マーカー |
| `question-bank.md` | 本横断の出題済みインデックス（空テーブル） |
| `removed-questions.md` | 退避問題の保管場所（空テーブル） |
| `.gitignore` | ローカル設定・中間ファイルの除外 |
| `PracticeTestBulkQuestionUploadTemplate_v2.csv` | Udemy 17カラム形式の参考ファイル |

**既存ファイルは絶対に上書きしません。** 存在するものは skip して報告します。何度実行しても安全なので、テンプレートに新ファイルが追加されたあとの差分適用にも使えます。

## ステップ1: 試験仕様のヒアリング

引数から `CERT_ID` を取り、残り7項目をユーザーに聞きます。引数が無ければ `CERT_ID` も聞きます。

| プレースホルダ | 聞くこと | 既定値 |
|---|---|---|
| `CERT_ID` | 試験番号（ディレクトリ名・コースタイトルに使う短い ID） | — |
| `CERT_NAME` | 正式名称（公式表記） | — |
| `VENDOR` | ベンダー。`anthropic` / `microsoft` / `github` / `cloudflare` / `ipa` / `generic` から選ぶ | — |
| `STUDY_GUIDE_URL` | 学習ガイド／試験ガイドの URL | — |
| `EXAM_MINUTES` | 試験時間（分） | — |
| `PASS_SCORE` | 合格スコア | — |
| `MOCK_EXAMS` | フル模試の本数 | `6` |
| `QUESTIONS_PER_EXAM` | 1本あたりの問題数 | `50` |

ヒアリングのコツ:

- **`MOCK_EXAMS` は6が上限。** Udemy の演習テスト専用コースは最大6テストまで作れる
- **`QUESTIONS_PER_EXAM` は実試験の問題数に合わせるのが望ましい**（本番相当のフル模試になる）。実試験が60問なら60にする
- `VENDOR` が一覧に無い場合は `generic` を選ぶ。調査は WebSearch → WebFetch のレシピで動く
- ドメイン配分は**ここでは聞かない。** `/udemy-exam-prep:create-sections` が学習ガイドから確定させる

## ステップ2: テンプレートの展開

収集した値でスクリプトを実行します。

```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/init_course.py" \
  --dest . \
  --cert "<CERT_ID>" \
  --cert-name "<CERT_NAME>" \
  --vendor "<VENDOR>" \
  --study-guide "<STUDY_GUIDE_URL>" \
  --exam-minutes <EXAM_MINUTES> \
  --pass-score <PASS_SCORE> \
  --mock-exams <MOCK_EXAMS> \
  --questions-per-exam <QUESTIONS_PER_EXAM>
```

出力例:

```
  created: .gitignore
  created: CLAUDE.md
  created: PracticeTestBulkQuestionUploadTemplate_v2.csv
  created: question-bank.md
  created: removed-questions.md
  created: sections.md
OK: 6 created, 0 skipped
```

スクリプトは未知のプレースホルダが残っていたら `InitError` で止まります（置換漏れの取りこぼしを防ぐ）。

## ステップ3: 展開結果の確認

`created` / `skipped` の一覧をそのままユーザーに提示します。

front matter が読めることを確認します。

```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/profile.py" sections.md
```

**この時点では `domains` が未確定なので FAIL（exit 1）が正常です。** 「必須キー 'domains' がない」等のエラーだけが出ていることを確認してください。他のエラー（`vendor` が未対応、`mock_exams` が0 など）が出ていたら、ヒアリングした値が間違っているので `sections.md` を直します。

## ステップ4: 次ステップの提示

```
プロジェクトを初期化しました。

【生成されたファイル】
（created の一覧）

【スキップしたファイル】
（skipped の一覧。既存のものは上書きしていません）

次のステップ:
  /udemy-exam-prep:create-sections <CERT_ID>
    → 学習ガイドから試験ブループリントを起草し、front matter の domains を確定します
      （R1 レビュー断面でいったん停止します）

ワークフロー全体像は生成された CLAUDE.md の「ワークフロー全体図」を参照してください。
```

## 一次情報源が PDF で配布されている場合

`vendor: anthropic` のように試験ガイドが PDF 配布のケースでは、初期化のついでに PDF を `research/` に保存してテキスト化しておくと `create-sections` が楽になります。

```bash
mkdir -p research
curl -sL -o "research/<CERT_ID>-Exam-Guide.pdf" "<PDF の URL>"
python - << 'PY'
import pdfplumber
src = "research/<CERT_ID>-Exam-Guide.pdf"
dst = "research/<CERT_ID>-Exam-Guide.txt"
with pdfplumber.open(src) as pdf:
    parts = []
    for i, page in enumerate(pdf.pages, 1):
        parts.append(f"===== PAGE {i} =====")
        parts.append(page.extract_text() or "")
open(dst, "w", encoding="utf-8").write("\n".join(parts))
print("pages:", len(pdf.pages))
PY
```

PDF の直 URL が分からない場合は、認定ページを WebFetch して「ページ上の全ハイパーリンクの完全な URL を列挙して」と頼むと得られます。

## エラー時の対処

| 症状 | 対処 |
|------|------|
| `FAIL: テンプレートディレクトリが無い` | プラグインが正しく導入されていない。`/plugin install udemy-exam-prep@shiro-plugin-marketplace` を確認 |
| `FAIL: 値が渡されていないプレースホルダ` | ヒアリングが不足。8項目すべてを CLI に渡す |
| `FAIL: 未知のプレースホルダ {{XXX}}` | テンプレートとスクリプトの `PLACEHOLDERS` が不整合。プラグイン側の不具合 |
| すべて `skipped` になる | 既に初期化済み。ファイルを消したい場合はユーザーが明示的に削除する |
| `profile.py` が `domains` 以外のエラーを出す | ヒアリング値の誤り。`sections.md` の front matter を直す |

## 厳守ルール

1. **既存ファイルを上書きしない** — スクリプトが skip するので、それを覆す操作（先に削除する等）を勝手に行わない
2. **ドメイン配分はここで決めない** — `create-sections` が学習ガイドから確定させる
3. **`MOCK_EXAMS` は6以下** — Udemy の制約
4. **展開後に `profile.py` を通す** — 目視確認で済ませない

## 関連スキル

- 次に呼ぶスキル: [[create-sections]] — 試験ブループリントの確定
- 調査レシピ: [[research-cert-docs]] — ベンダー別の一次情報源
