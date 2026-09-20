---
name: research-cert-docs
description: 認定資格の試験対策で、サブトピックごとに一次情報源を徹底調査するレシピ。sections.md front matter の vendor と primary_sources に従って情報源を切り替え、検索→fetch→sources.md 記録のフローを規定する。anthropic / microsoft / github / cloudflare / ipa / generic のベンダー別レシピを持つ。
---

# research-cert-docs

問題集の品質は **公式ドキュメントの調査の質** で決まる。推測や一般知識ではなく、必ず一次情報源から事実を引いてくる。

## ステップ1: 情報源を決める

> 本スキルのベンダー別レシピ表と sources.md フォーマットは、**このスキルが唯一の定義元**。
> [[doc-researcher]] 等は再掲せず参照する。

`sections.md` の front matter を読む。

1. `primary_sources` があればそれが最優先。`priority` の昇順に使う（プロジェクト側の宣言が常に勝つ）
2. `vendor` を見て下表のレシピで補う

| vendor | 優先1 | 優先2 | 優先3 |
|---|---|---|---|
| `anthropic` | 公式 Exam Guide PDF（プロジェクト内に保存したもの） | `docs.claude.com` を WebFetch（Claude Code / Agent SDK / Claude API / MCP） | `modelcontextprotocol.io` を WebFetch |
| `microsoft` | `microsoft_docs_search` / `microsoft_docs_fetch`（MCP） | context7 `query-docs`（関連 SDK） | WebFetch（`learn.microsoft.com/search/?terms=`） |
| `github` | WebFetch（`docs.github.com`） | context7 `query-docs` | WebSearch |
| `cloudflare` | `search_cloudflare_documentation`（MCP） | WebFetch（`developers.cloudflare.com`） | context7 `query-docs` |
| `ipa` | WebFetch（`www.ipa.go.jp` のシラバス・過去問 PDF） | WebSearch | — |
| `generic` | WebSearch で公式ドメインを特定 → WebFetch | context7 `query-docs` | — |

**`vendor` が上表に無い値だった場合**は `generic` 行で進め、「vendor `<値>` は既知レシピが無いため generic で調査した」と警告を出す。

**二次情報（個人ブログ・受験記・まとめ記事・動画）は、難易度と出題傾向の校正にのみ使う。問題の出典には使わない。** 出典 URL 欄に二次情報を書いてはいけない。

## ステップ2: 利用可能な調査ツール

| ツール | 用途 | 入力例 |
|--------|------|--------|
| `WebFetch` | URL からページ取得。取得と同時に prompt で必要な事実だけ抜ける | `https://docs.claude.com/en/docs/claude-code/settings` |
| `WebSearch` | 公式ドメインの特定、一次情報源の入口探し | `"Claude Agent SDK hooks PostToolUse"` |
| `microsoft_docs_search` MCP | Microsoft Learn 全文検索（短いスニペット返却） | `"Azure AI Search hybrid search"` |
| `microsoft_docs_fetch` MCP | Microsoft Learn ページの完全 markdown 取得 | `https://learn.microsoft.com/azure/...` |
| `search_cloudflare_documentation` MCP | Cloudflare 開発者ドキュメント検索 | `"Durable Objects alarms"` |
| context7 `resolve-library-id` + `query-docs` | OSS ライブラリのドキュメント | `modelcontextprotocol`, `langchain` |
| ローカル PDF | 公式 Exam Guide 等。`pdfplumber` でテキスト化して `grep` / `Read` で引く | `research/<CERT>-Exam-Guide.txt` |

**実際の MCP ツール名は環境依存** — `mcp__plugin_microsoft-docs_microsoft-learn__microsoft_docs_search` のように `plugin_` プレフィックスが付くことが多い。本文では機能名で言及する。

### 公式 PDF をテキスト化する

```bash
python - << 'PY'
import pdfplumber
src, dst = "research/<CERT>-Exam-Guide.pdf", "research/<CERT>-Exam-Guide.txt"
with pdfplumber.open(src) as pdf:
    parts = []
    for i, page in enumerate(pdf.pages, 1):
        parts.append(f"===== PAGE {i} =====")
        parts.append(page.extract_text() or "")
open(dst, "w", encoding="utf-8").write("\n".join(parts))
print("pages:", len(pdf.pages))
PY
```

## ステップ3: サブトピック1つに対する調査レシピ

```
1. 検索クエリ作成（英語キーワード3〜5語）
   機能名・API名・設定キー名をそのまま使う（訳語では公式に当たらない）

2. 一次情報源で検索
   - 学習ガイドやブループリントが PDF で配布されている資格は、まずそれを grep する
   - ドキュメントサイトは MCP 検索 → 無ければ WebFetch
   - /training/ や /tutorials/ のような学習パスは試験出題と直結するので優先

3. 候補ページから、サブトピックに直結する事実を抽出
   - 機能名・API エンドポイント・設定キー・フラグ名・既定値・制約事項・数値
   - 「何がアンチパターンか」も同じ重みで拾う（不正解選択肢の材料になる）

4. 二次情報源で裏取り（任意）
   - 同じ概念が両方に出てくれば信頼度が上がる

5. sources.md 用に記録
   - URL, タイトル, 取得日, このサブトピックに対する関連度（直接/間接）
```

### 現行ドキュメントの確認（陳腐化した事実を問題にしない）

- 製品のドキュメントが **現行版と旧構成（classic）版に分かれている**場合は現行側を正とする。旧側にしかない事実は digest に入れない。入れるなら「旧構成」と明記する（実績: 旧構成の前提を根拠に「必須」と出題し、現行では不要になっていて陳腐化した）
- **試験ガイドの出題範囲に載っていない旧概念**（廃止・移行済みの機能、旧試験の題材）は、digest に「範囲外」と注記して問題化しない
- 「廃止予定」「retirement」の記述は、**すでに廃止済みか**を最新の日付で確認してから書く
- **具体的な数値**（上限・文字数・サイズ・解像度・料金）はページ上の値を写し、値と出典 URL をセットで digest に残す。裏が取れない数値は digest に入れない

## ステップ4: 並列調査の単位

サブトピックは互いに独立しているので、[[doc-researcher]] エージェントを **サブトピック数だけ並列起動** する。各エージェントは自分のコンテキストで巨大ドキュメントを処理し、digest（事実リスト + URL）だけを親に返す。

```
Phase 1a（1回限り・全セクションで共有）
  ├─ Agent: doc-researcher (領域 1)
  ├─ Agent: doc-researcher (領域 2)
  ├─ ...
  └─ Agent: doc-researcher (領域 N)
       ↓ digests
  research/*.md に保存 → 全セクションの問題生成で再利用
```

## ステップ5: カバレッジ検証

調査終了後、以下を満たすか確認する。

```bash
for f in research/*.md; do
  echo "$f : URL=$(grep -cE 'https?://' "$f") lines=$(grep -c '' "$f")"
done
```

- [ ] 各 digest に**最低1つの一次情報源 URL** がある（URL=0 のファイルは推測で書かれている疑い → 再実行）
- [ ] 同じ URL を3つ以上の digest で使い回していない（粒度が荒すぎる兆候）
- [ ] digest が薄いものがない（→ 追加検索が必要）
- [ ] `sections.md` の Out-of-Scope に該当する事実が混ざっていない

## sources.md フォーマット

各セクションフォルダの `sources.md` は以下の構成で書く。

```markdown
# section01-XXX 出典

最終更新: YYYY-MM-DD

## 参照ドキュメント

| # | タイトル | URL | 取得日 |
|---|----------|-----|--------|
| 1 | Claude Code settings | https://docs.claude.com/en/docs/claude-code/settings | 2026-09-13 |
| 2 | Tool use with Claude | https://docs.claude.com/en/docs/build-with-claude/tool-use | 2026-09-13 |

## 問題と出典の対応

| 問題# | task_statement | tested_concept | シナリオ | 出典# |
|-------|---------------|----------------|---------|-------|
| 1 | 1.1 | stop_reason による継続判定 | S1 | 2 |
| 2 | 3.1 | CLAUDE.md の階層とスコープ | S2 | 1 |
```

## URL 寿命と保守

- 公式ドキュメントは URL 変更が頻繁。半年〜1年で 10% 程度が 404 になる経験則
- `sources.md` には**取得日**を必ず記録 → 再生成時の URL 検証で参照
- 試験ガイド改訂時は `sections.md` 更新と一緒に `sources.md` の URL 有効性も `curl -I` 等で軽くチェック

## ペアになるエージェント・スキル

- 実行する側: [[doc-researcher]] エージェント
- 出力を消費する側: [[question-author]] エージェント
