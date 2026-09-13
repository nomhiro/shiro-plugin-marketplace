---
name: create-udemy-course
description: Udemy に演習テストコースを新規作成し、タイトル・サブタイトル・説明文・学習目的・メッセージ等の基本設定を Playwright MCP で自動入力する。sections.md の front matter と CLAUDE.md から情報を組み立てる。スラッシュコマンド `/udemy-exam-prep:create-udemy-course` または「Udemy にコース作って」で起動。
---

# create-udemy-course

Playwright MCP を使って Udemy に演習テスト講座を作成し、基本設定を行うオーケストレータスキル。

実装の詳細（Playwright 操作、エラー処理）は [[udemy-bulk-upload]] に従います。このスキルはコース作成シナリオ固有の **入力整理** と **メッセージ生成** に集中します。

## 起動例

```
/udemy-exam-prep:create-udemy-course
Udemy にコース作って
/udemy-exam-prep:create-udemy-course https://www.udemy.com/instructor/course/XXX/manage/basics
```

## 前提条件

- Playwright MCP が利用可能（プラグイン同梱）
- Chrome ブラウザが閉じている（Playwright 起動の競合回避）
- `sections.md`（front matter 含む）と `CLAUDE.md` が記入済み

## 動作モード

| モード | 起動条件 | 実行ステップ |
|-------|----------|------------|
| **新規作成モード** | コース URL の指定なし | ステップ1〜7 全て |
| **既存コース更新モード** | 起動引数にコース URL あり / 「すでにコースは作ってあります」発言 | ステップ4（コース作成）をスキップ。ログイン後に対象URLへ直接遷移 |

既存コース更新モードでは、ユーザーが指定したサブページ（basics / goals / communications/messages）に応じて該当ステップだけを実行する。

## ステップ1: コース情報の準備

`sections.md` の front matter と `CLAUDE.md` から組み立てる。

```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/profile.py" sections.md
```

| 項目 | 雛形 / 出典 |
|------|------|
| **コース名**（60字） | `【認定資格練習問題集】{cert} {cert_name_ja または cert_name}` |
| **サブタイトル**（120字） | 出題領域の要約 + 「フル模試{mock_exams}回・計{mock_exams × questions_per_exam}問・全問詳細解説つき」 |
| **説明文**（200語以上） | 下記構成 |
| **カテゴリ** | IT とソフトウェア > IT資格（最も近いもの） |
| **言語** | 日本語 |
| **レベル** | すべてのレベル |

### 説明文の構成

1. コースの目的（1文）
2. 試験概要 — front matter の `exam_code` / `questions_per_exam` / `exam.minutes` / `exam.pass_score` / `exam.max_score` / 受験料 / 有効期限 / 配信方式
3. ドメインとウェイト（front matter の `domains`）
4. 問題集の構成 — 各演習テストの内容と問題数
5. **出題言語の設計とその理由** — front matter の `exam.language` が実試験に合わせて英語の場合、「本番と同じ英語出題＋全問日本語解説」という設計であることと、その根拠を明記する（受講者が最も知りたい差別化要素）
6. 解説の作り — 正解の理由に加えて不正解選択肢が何を意味しどこが違うかまで説明し、出典 URL を付けていること
7. 学習内容（`sections.md` のセクション一覧）

組み立てた情報を**ユーザーに提示して確認を取る**。確認が取れたら `udemy-course-meta.md` に書き出す。これがサイト入力時の Source of Truth になる。

## ステップ2: ログイン

[[udemy-bulk-upload]] の「ステップ2: ブラウザログイン」に従う。

**ログインが必要な状態に当たったら、そこで停止してユーザーに依頼する。** 資格情報を自分で入力してはいけない。

## ステップ3: 講師ダッシュボードに移動

1. `browser_navigate https://www.udemy.com/instructor/courses/`
2. `browser_snapshot` でページ構造を確認

## ステップ4: 新しいコースを作成

1. 「新しいコース」ボタンを `browser_snapshot` で特定して `browser_click`
2. コースタイプ選択で「**演習テスト**」(Practice Test) を選択
3. コースタイトル入力欄にステップ1で準備したコース名を入力
4. 「コースを作成」をクリック
5. コース管理ページへの遷移を確認

各ステップで `browser_snapshot` を実行して進捗を確認する。要素が見つからなければ `browser_take_screenshot` でデバッグする。

## ステップ5: コースの基本設定（basics ページ）

URL: `/instructor/course/<id>/manage/basics/`

- タイトル（60文字制限）
- サブタイトル（120文字制限）
- 説明文（最低200語）
- 言語（日本語）/ レベル（すべてのレベル）/ カテゴリ・サブカテゴリ

入力手順:
1. `browser_snapshot` で入力欄を特定
2. `browser_click` でフォーカス
3. `browser_type` で値入力（ドロップダウンは `browser_select_option`）
4. 全項目入力後、「保存」を `browser_click`

### browser_type は全置換動作（fill）

`browser_type` は内部的に Playwright の `fill()` を呼ぶため、**既存テキストを全置換**する。追記したい場合でも「フルテキストを入れ直す」ようにする。`End` キー押下 + `browser_type` の組み合わせは効かない。

### 保存ボタンの ref はページ遷移なしで再採番されることがある

basics → 別ページに移動した後で保存ボタンの ref が `e51 → e49` のように変わるケースを確認。「保存」名で直前 snapshot から ref を取り直してから click する。ref が古いと **隣の「コース設定」リンクに当たって `confirm` ダイアログ（「変更内容は保存されない可能性があります」）が出る**事故になる。

事故った場合の復旧:
1. `browser_handle_dialog accept=false`（このページに留まる）
2. 直前 snapshot で「保存」ボタンの最新 ref を取得
3. 再度クリック

### コース画像のアップロード

Udemy 仕様: **750×422 ピクセル / .jpg/.jpeg/.gif/.png / テキスト含む画像不可**

#### 入力画像の正規化

ユーザーが渡した画像は十中八九「サイズが違う / バイト数が大きすぎる / アスペクト比が違う」のいずれか。`PIL` で正規化してから渡す。

```python
from PIL import Image

src = 'courseImage.png'
im = Image.open(src).convert('RGB')
W, H = im.size

TARGET_W, TARGET_H = 750, 422
target_ratio = TARGET_W / TARGET_H
cur_ratio = W / H

if cur_ratio > target_ratio:
    new_w = int(H * target_ratio)
    x = (W - new_w) // 2
    im = im.crop((x, 0, x + new_w, H))
else:
    new_h = int(W / target_ratio)
    y = (H - new_h) // 2
    im = im.crop((0, y, W, y + new_h))

im = im.resize((TARGET_W, TARGET_H), Image.LANCZOS)
im.save('courseImage-udemy.jpg', 'JPEG', quality=90, optimize=True, progressive=True)
```

- **JPEG 推奨**（写真風画像なら 80KB 前後に収まる）
- PNG だと写真は数百KB〜数MBに膨らみアップロード失敗の原因になる
- 元画像が RGBA の場合は `convert('RGB')` 必須（JPEG は alpha 非対応）

#### S3 multipart アップロードエラー対処

UI に「One or more of the specified parts could not be found...」と出る場合、Udemy 裏側の AWS S3 multipart アップロードが失敗している。

| 原因 | 対処 |
|------|------|
| ファイル名に日本語・空白・特殊文字 | 半角英数のみに改名（例: `course-image.jpg`） |
| ファイルが大きすぎる（>2MB） | 上記 PIL スクリプトで JPEG quality 90 に変換 |
| アップロード途中の残骸が残っている | **ページをリロード**してから再アップ |
| 広告ブロッカー/プライバシー拡張が S3 リクエストを遮断 | シークレットウィンドウで開き直す |
| VPN / 企業プロキシで S3 へのマルチパート POST がドロップ | VPN を切る |
| ブラウザ依存 | Edge / Firefox / Safari で試す |

#### 規約上の注意（テキスト・ロゴ）

Udemy ガイドラインは画像内に以下を含めることを禁止している。

- 任意のテキスト（コースタイトル含む）
- 第三者のロゴ・商標（審査でリジェクトされやすい）
- 「Udemy」ロゴを自前画像内に重ねること

ユーザーが渡した画像に上記が含まれている場合は、**アップロード前に必ず指摘**する。リジェクト後の作り直しコストが高い。

## ステップ5.5: 想定する学習者ページ（goals ページ）

URL: `/instructor/course/<id>/manage/goals/`

- **学習目的（Learning Objectives）** — 最低4個、推奨7〜14個（160文字制限）
- **必須条件（Requirements）** — 1個以上
- **対象受講者（Target Audience）** — 1個以上

各セクションは「解答1」textbox + 「応答に追加します」ボタンで構成。

### 「応答に追加します」ボタンは空 textbox があると効かない

連続クリックで一気に N 個増やそうとしても、最後の空 textbox があると2回目以降が無視される。必ず**「直前の textbox に値を入れてから次の追加ボタンを押す」**順序で進める。

```
type(解答N) → click(応答に追加します) → type(解答N+1) → click(応答に追加します) → ...
```

### ref の予測パターン

新しく追加される textbox の ref は、**同一セクション内では +15 ずつ**増える規則。

| イベント | ref の動き |
|---------|----------|
| 最初の追加（セクション初の動的追加） | 既存ref から大ジャンプ（例 e140 → e393） |
| 同一セクション内2回目以降 | **+15ずつ規則的に増える**（e393, e408, e423, …） |
| 別セクションでの最初の追加 | 再び大ジャンプ |

snapshot は最初の追加直後だけ取り、それ以降は予測 ref で `browser_type` を実行。失敗したら snapshot で再確認するフォールバック方式が効率的。

### textbox の name 重複

3セクションすべてに「解答1」が存在する。`getByRole('textbox', { name: '解答1' })` は曖昧マッチになるため、**必ず ref で指定**する。「応答に追加します」ボタンも3個あり、`first()` / `nth(1)` / `nth(2)` を使う。

## ステップ6: コースメッセージの設定（communications/messages ページ）

`sections.md` の情報をもとに動的に組み立てる。

### 歓迎のメッセージ（構成）

1. 試験対策コースへの歓迎と感謝
2. コースの概要（問題数、演習テスト数）
3. 学習の進め方（4ステップ: 順番に解く → 解説確認 → 復習 → 繰り返し）
4. Q&Aセクションへの案内
5. 合格祈願

### お祝いのメッセージ（構成）

1. コース修了のお祝いと感謝
2. 本コースで習得した知識の要約（front matter の `domains` の一覧）
3. 試験に向けたアドバイス（苦手分野の復習、落ち着いて解答、合格スコアは front matter の `exam.pass_score` を使う）
4. 合格祈願と謝辞

## ステップ7: 結果報告

- 作成したコースの URL をユーザーに報告
- 設定した内容の一覧を表示
- `udemy-course-meta.md` に実施結果（コース URL・入力済み項目・未実施項目）を追記

## 注意事項

- Udemy UI はアクセシビリティツリーベース → `browser_snapshot` の ref / role / name を使う（CSS セレクタ禁止）
- 入力が長い説明文は一度に投入せず、適宜 `browser_snapshot` で確認
- 既存コースの「テスト追加」だけが目的なら本スキルではなく [[upload-practice-tests]] を使う
- `browser_type` は `fill()` で全置換動作 — 既存値への追記はできない
- ボタン/リンクの ref はページ内 DOM 操作で再採番されることがある。click 前に「保存」「応答に追加します」など **name で snapshot から最新 ref を取得**する
- ref 直指定が失敗したら snapshot を取り直すフォールバック。CSS selector / aria-label セレクタは Udemy の動的構造では当たらないことが多い
- 大きな画像（>2MB）は S3 multipart で失敗しやすい。PIL で 750×422 / JPEG quality 90 に正規化してから渡す
- 画像にテキスト・第三者ロゴが含まれる場合はアップロード前にユーザーへ警告
- **演習テストを追加するにはコースが有料設定済みである必要がある**
- **審査提出と公開ボタンは押さない。** ここは人が判断する工程

## 関連スキル

- [[udemy-bulk-upload]] — Playwright 操作レシピ
- [[upload-practice-tests]] — 既存コースへのテストアップロード
