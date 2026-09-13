---
name: udemy-bulk-upload
description: Udemy 演習テストコースに quiz.csv を一括アップロードするためのPlaywright操作レシピ。コース作成、テスト追加、設定値、CSV事前検証、既存テスト入れ替えのAPIワークアラウンドを含む。
---

# udemy-bulk-upload

Udemy 演習テストコースの作成と quiz.csv アップロードは、Playwright MCP（`@playwright/mcp`）で自動化する。アクセシビリティツリーベースで動作するため、`browser_snapshot` で取得した ref / role / name を使う（CSS セレクタは使わない）。

## 前提条件

- Playwright MCP が利用可能（`udemy-exam-prep` プラグインが `.mcp.json` で同梱している）
- Chrome ブラウザが閉じている（Playwright 起動時の競合回避）
- 各セクションフォルダに quiz.csv が作成済み
- コースが**有料設定済み**（無料コースでは演習テストを追加できない仕様）

## Udemy 側の制約

| 制約 | 内容 |
|---|---|
| テスト数 | 演習テスト専用コースは**最大6テスト** |
| 無料コース | 演習テストを追加できない。先に有料設定にする |
| 公開済みテスト | 個別問題の削除・編集が API でできない（後述のワークアラウンド） |

## ステップ1: CSV 事前検証

アップロード前に必ず全 quiz.csv を検証する。FAIL があれば修正してからアップロードする。

```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/validate_quiz_csv.py" section0*/quiz.csv
```

規約の詳細は [[quiz-csv-format]] を参照。

## ステップ2: ブラウザログイン

```
1. browser_navigate https://www.udemy.com/join/login-popup/
2. ユーザーに「手動でログインしてください。2FA完了後に教えてください」と伝える
3. ユーザー応答を待つ
4. browser_snapshot でログイン状態を確認
```

**資格情報を自分で入力してはいけない。** ログインが必要な状態に当たったら、そこで停止してユーザーに依頼する。

## ステップ3: コース管理ページへ移動

```
1. browser_navigate https://www.udemy.com/instructor/courses/
2. browser_snapshot で該当コースのリンクを探す
3. クリックしてコース管理ページに入る
```

## ステップ4: 演習テストの追加（最大6本）

```
1. カリキュラム編集ページで「新しいカリキュラム項目」をクリック
2. 「演習テストを追加」を選択
3. タイトル入力（sections.md のセクション名のみ。「セクションN:」プレフィックスは含めない）
4. 2つ目以降は、直前のテスト下部の「新しいカリキュラム項目」ボタンから追加
```

## ステップ5: 各テストの設定

各演習テストの編集ページ（URL に `quizId=YYYY` を含む）で設定する。

| 項目 | 値 |
|------|--------|
| 時間（分） | `sections.md` front matter の `exam.minutes` をそのまま（本番と同条件）。`exam.minutes` が無い資格では `問題数 × 1.5` を使う |
| 合格最低点（%） | 70 |
| 質問と回答の順序をランダム化 | **ON**（必須） |

**Playwright の注意点:**
- 「質問と回答の順序をランダム化」チェックボックスはラベル要素に遮られて直接クリックできない。**親の generic 要素またはラベルテキスト**をクリックする
- 設定変更後は必ず「保存」ボタンを `browser_click`

## ステップ6: CSV 一括アップロード

```
1. テスト編集ページで「質問を追加」→「一括アップロード」→「CSVファイルのアップロード」
2. ネイティブのファイル選択ダイアログが開く（Modal state: [File chooser]）
3. browser_file_upload で対応する quiz.csv のパスを渡す
4. アップロード完了まで8〜10秒待機（browser_wait_for で「アップロード完了」テキストを待つ）
5. 成功メッセージを確認してダイアログを閉じる
6. 「公開」操作（必要なら）
```

## 既存テストの問題を入れ替える場合

**重要:** Udemy API は**公開済みテストの個別問題の削除・編集ができない**。`is_draft: true` や `is_published: false` を PATCH しても、問題操作 API は400を返す。

### 正解の手順: テスト自体を削除→再作成

`browser_evaluate` 経由で以下を実行する。

```javascript
const csrfToken = document.cookie
  .split(';')
  .find(c => c.trim().startsWith('csrftoken='))
  .split('=')[1];

const headers = {
  'X-CSRFToken': csrfToken,
  'Content-Type': 'application/json',
};

// 非公開にしてからテスト本体を削除
await fetch(`/api-2.0/courses/${courseId}/quizzes/${quizId}/`, {
  method: 'PATCH',
  headers,
  body: JSON.stringify({ is_published: false }),
});
await fetch(`/api-2.0/courses/${courseId}/quizzes/${quizId}/`, {
  method: 'DELETE',
  headers,
});
```

**ポイント:**
- API DELETE 後もカリキュラムページにテスト枠が残ることがある → UI の「削除」ボタンで確実に消す
- テスト削除はバックグラウンド処理。直後に新規テスト作成するとカウントエラーが出る場合がある（数秒待ってリトライ）

その後、ステップ4〜6 で再作成する。

### テストタイトルだけ変更（削除不要）

```javascript
await fetch(`/api-2.0/courses/${courseId}/quizzes/${quizId}/`, {
  method: 'PATCH',
  headers: {
    'X-CSRFToken': csrfToken,
    'Content-Type': 'application/json',
  },
  body: JSON.stringify({ title: '新しいタイトル' }),
});
```

## エラーハンドリング

| 症状 | 原因 | 対処 |
|------|------|------|
| CSV アップロード後「ヘッダーが正しくありません」 | BOM 混入 | `utf-8`（BOM 無し）で書き直し。`write_rows` を使う |
| アップロード後「行Nがフォーマット不正」 | 17カラム不一致 | `validate_quiz_csv.py` を再実行 |
| multi-select 取り込み失敗 | 正解が1個しかない | `multiple-choice` に変更 |
| 演習テストを追加できない | コースが無料設定 | 先に有料設定にする |
| 7本目を追加できない | 演習テストは最大6本 | 仕様。本数を6以下にする |
| ファイル選択ダイアログが開かない | Modal state が違う | `browser_snapshot` で状態確認、UI操作からやり直し |
| クリックできない要素 | ラベルに遮られている | 親の generic 要素をクリック |

## ペアになるスキル

- アップロード前の CSV 品質は [[quiz-csv-format]] で保証
- セクション横断のオーケストレーションは [[upload-practice-tests]]
