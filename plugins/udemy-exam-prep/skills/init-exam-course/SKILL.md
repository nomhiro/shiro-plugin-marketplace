---
name: init-exam-course
description: 試験番号を引数に、新しい試験対策問題集プロジェクトをテンプレートから初期化する。CLAUDE.md / sections.md / question-bank.md / removed-questions.md / AUTHOR-BRIEF.md / research/AUTHORING-GUARDRAILS.md / .gitignore / Udemy CSV 参考ファイルを展開し、試験仕様をプレースホルダ置換で埋める。既存ファイルは上書きしない。スラッシュコマンド `/udemy-exam-prep:init-exam-course CCA-F` または「CCA-F の講座プロジェクトを作って」で起動。
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
| `AUTHOR-BRIEF.md` | 作問エージェント共通ブリーフの雛形。**資格固有の方針を書き足して使う**（並列作問で全エージェントに読ませる1枚） |
| `research/AUTHORING-GUARDRAILS.md` | 作問ガードレールの雛形。digest の「未解決の論点」を畳み込む先 |
| `PracticeTestBulkQuestionUploadTemplate_V2.2.csv` | Udemy 17カラム形式の参考ファイル |

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
  created: AUTHOR-BRIEF.md
  created: CLAUDE.md
  created: .gitignore
  created: PracticeTestBulkQuestionUploadTemplate_V2.2.csv
  created: question-bank.md
  created: removed-questions.md
  created: research/AUTHORING-GUARDRAILS.md
  created: sections.md
OK: 8 created, 0 skipped
```

テンプレートはサブディレクトリを保ったまま展開されます（`research/` 配下など）。

スクリプトは未知のプレースホルダが残っていたら `InitError` で止まります（置換漏れの取りこぼしを防ぐ）。

## ステップ3: 展開結果の確認

`created` / `skipped` の一覧をそのままユーザーに提示します。

**展開直後にやること（ユーザーに伝える）:**

1. `sections.md` の front matter の任意キーを埋める
   - `forbidden_sources` — 出典に使ってはいけないホスト（受験申込の製品ページ・転送される旧ホスト）
   - `source_titles` — `sources.md` に出すホストの表示名
   - `guide_citation` — Exam Guide だけが根拠の事実に使う出典表記
   - `max_per_concept` — 同一概念を何本まで再利用してよいか
   - `style` — 解説の書式の機械検査。**雛形では正誤印と出典 URL 直後の空白を有効にしてある。**
     消したり `{}` にしたりしない（正誤印の表記統一・訳・文体が検査されなくなり WARN が出る）。
     問題文と解説の言語が違う講座は、コメントアウトしてある訳マーカーと文体の行を有効にする
   - `glossary` — 原語で書く用語と使ってはいけない訳語。**製品名・サービス名・役割名のうち
     和訳・カタカナ化されやすいものを作問前に列挙する。** 「原語のまま書く」という散文の
     方針だけでは守られない（実績: 300問で約400件の和訳・カタカナ化が混入した）。
     digest がそろった時点で追記してもよいが、**作問ブリーフの契約文を生成する前に確定させる**
2. `AUTHOR-BRIEF.md` に**資格固有の方針**を書き足す（出題言語・用語表記・distractor の型）。
   機械検査される基準（§4-1 選択肢の長さ / §7-1 正解肢の文面）は変えない
3. `research/AUTHORING-GUARDRAILS.md` は digest 作成後に埋める（[[create-section]] の Step 2 の後）

front matter が読めることを確認します（`glossary` の形の誤りもここで検出されます）。

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
