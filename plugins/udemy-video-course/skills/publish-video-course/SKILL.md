---
name: publish-video-course
description: 完成した講座動画（mp4）を Udemy の動画講座に載せる。セクションと講義の並び、動画のアップロード（10MB を超えるファイルをページ内スクリプトで選ぶ）、記事の講義（ボーナス レクチャー）、小テスト（Udemy のクイズ＝simple-quiz）の入力、題名の改名と検証、差し替え、審査に出す前の最終点検、審査結果への対応までを、ブラウザの画面の操作（Claude in Chrome）で行う。読み取りは Udemy の内部 API。公開・審査への提出・価格は制作者が行う。「Udemy に動画講座を作って」「動画をアップロードして」「小テストを Udemy に入れて」「講義の動画を差し替えて」「審査の指摘に対応して」で起動。
allowed-tools: Read, Write, Glob, Grep, Bash
---

# publish-video-course

完成した講座動画を Udemy の**動画講座**に載せるスキル。演習テスト講座（CSV の一括アップロードがある）は
`udemy-exam-prep` の `create-udemy-course` / `udemy-bulk-upload` が担当する。コースの基本情報の入力
（長文の入れ方・コース画像・規約上の注意）は `create-udemy-course` と同じなので、そちらを読む。
このスキルは**動画講座に固有の部分**だけを持つ。

実績は次の2つ。
- 座学中心の講座（2026-10）: 座学 241 本・約 19 時間・12 セクション。枠の作成から動画のアップロード（失敗 0）、小テスト 51 本・158 問。書き込みは API
- ハンズオン中心の講座（2026-10）: 10 セクション・講義 65（動画 64＋記事 1）・小テスト 24・約 5 時間半。**書き込みはすべて画面の操作**（API の POST は止められた）。審査の差し戻し1件（ボーナス レクチャーの講義名）に対応

## 🔴 してはいけないこと

- **公開・審査への提出（再提出を含む）・価格・クーポン・プロモーションの設定はしない。** 制作者が内容を確かめて自分で押す
- **取り消せない削除（講義・セクション・動画・小テスト）はしない。** 消す対象の一覧を作って制作者に頼み、消えたかを読み取りで確かめる（§9）
- **審査担当者や受講者への返信は、文面を見せて制作者の了解を得てから送る**（送ると取り消せない）
- **ログイン中の Chrome のタブを閉じない・別のページへ移動しない**（アップロード中に移動すると止まる）。作業は自分で開いたタブで行う
- ファイルサーバーは **127.0.0.1 にだけ** bind する。置き場の外を配らない。使い終わったら PID を指定して止める
- ログインの画面が出ても、パスワードは入れない。制作者にログインを頼む

## 0. 始める前に

- **ブラウザが2つつながっているときは、自分で選ばない。** 接続中のブラウザの一覧を制作者に見せて選んでもらう。
  選んだブラウザが Udemy にログインしていないこともある（2026-10-24: 名前が入れ替わっていて、選んだ方はログイン画面になった）
- **最初に読み取り（GET）を1回して、ログインと権限を確かめる。** 403 か、ページがログイン画面に移ったら、書き込みに進まず制作者に伝える
- タブグループが見えなくなったら、つなぎ直しを制作者に頼む。書き込む原稿（説明文・小テスト）は、先に手元のファイルに書いておく（途中で切れても失わない）
- 講座の方針（`course.yaml` か講座の CLAUDE.md）を読む: 講義名の印（実践の頭の「【ハンズオン】」など）、字幕を上げるか、小テストの形

## 流れ

1. **カリキュラムを作る**（講座側）：セクション＝章、講義＝動画1本、小テストの位置、の並びを決める
2. **コースの枠**：`create-udemy-course` の手順で基本情報・学習目標・前提・対象者・メッセージを入れる。**旧い下書きを流用するときは、最初に今の説明・学習目標・前提・対象者を読み、作り直しの対象に入れる**（§7）
3. **セクションと講義**を作る（§2）
4. **動画**をアップロードする（§3。ファイルサーバー＋ページ内スクリプト）
5. **記事の講義**（ボーナス レクチャーなど）を作る（§4）
6. **小テスト**を入れる（§5）
7. **検証**：並び・動画の処理・公開状態・小テストの正解と文面を、原稿と全数で突き合わせる（§6）
8. **審査に出す前の最終点検**（§7）をして、制作者に報告する（提出は制作者）
9. 審査の結果が来たら、指摘に対応する（§8）

## 1. カリキュラム（講座側）

- 制作の一覧表から作る。区切りだけの短い動画（間の札など）は講義にしない
- **講義名・セクション名に番号を入れない**（制作者の指示。制作中のファイル名・一覧は番号つきでよい）。
  「1-2-3 〇〇」→「〇〇」。章の全体像のような番号だけで区別していた題名は「全体像：<章名>」のように中身の名前にする。
  題名は 80 字以内
- 座学と実践が混ざる講座は、**実践の講義名の頭に印を付ける**（は「【ハンズオン】」。小テストの名前には付けない）
- 組（まとまり）の名前は、**設計書ではなく動画の中身**に合わせる。設計書と動画がずれていた例がある
  （設計書の「プライバシー」の組の実体が「公平性」だった）。補正表を講座側に持つ
- アップロード用に、セクションごとのフォルダ（`00`, `01`, …。同じ章の2本目は `08b` のように文字を付ける）へ、
  講義の順に並ぶ名前（`01_<slug>.mp4`）で置く。本数が多いときは**ハードリンク**にする（容量を食わない）

## 2. セクションと講義を作る

書き込みには2つの道がある。**既定は画面の操作。** ページ内からの API の POST は、制作者の許可があっても
自動モードの判定で止められることがある（2026-10-18）。読み取り（GET）は API で行ってよい。

### 2-1. 画面の操作（既定）

1. カリキュラム画面のいちばん下の「＋ セクション」→ タイトルを入れて「セクションを追加」。学習目標の欄は空でよい
   - **途中や先頭に入れるとき**: セクションの見出しの少し上にマウスを置くと「＋」が出る。押すとその位置に欄が開く（ドラッグで並べ替えなくてよい）
2. そのセクションの**下端の**「＋ カリキュラム項目」→「レクチャー」→ タイトルを入れて「レクチャーを追加」
   - セクション見出しの近くの「カリキュラム項目を追加」は、セクションの**先頭**に入るので使わない
   - 追加するたびにボタンの位置が下にずれる。座標で押さず、`find` で「最後の『＋ カリキュラム項目』」を探して押す
3. 題名を直すときは、講義の行の鉛筆（編集）→ 入力欄を全選択して打ち直す →「レクチャーを保存」
- コース作成時に既定の「セクション1」「レクチャー1」がある。名前を変えて1本目に使い回す
- **セクションを消しても中の講義は消えない**（講義は「一時的なセクション」に移る）。消すなら講義を先に（§9）

### 2-2. API（書き込みが許されている環境だけ）

Claude in Chrome の `javascript_tool` で、ログイン済みの管理画面
（`https://www.udemy.com/instructor/course/<courseId>/manage/curriculum/`）から呼ぶ。

```js
const csrf = document.cookie.split('; ').find(c => c.startsWith('csrftoken=')).split('=')[1];
window.__api = async (m, p, b) => {
  const r = await fetch(p, {method: m, credentials: 'include',
    headers: {'Content-Type': 'application/json', 'X-CSRFToken': csrf, 'Accept': 'application/json'},
    body: b ? JSON.stringify(b) : undefined});
  let j = null; try { j = await r.json(); } catch (e) {}
  return {s: r.status, j};
};
```

| 操作 | API |
|---|---|
| セクションを作る | `POST /api-2.0/users/me/taught-courses/<courseId>/chapters/` `{title}` |
| 講義を作る | `POST /api-2.0/users/me/taught-courses/<courseId>/lectures/` `{title}` |
| 題名を変える | `PATCH /api-2.0/users/me/taught-courses/<courseId>/chapters|lectures/<id>/` `{title}` |
| 並びを決める | `PUT /api-2.0/courses/<courseId>/instructor-curriculum-items/` 本文 `{"items": "<JSON 文字列>"}`。中身は `[{id, class: "chapter"|"lecture"|"quiz", is_published: true}]`（クイズは `type: "simple-quiz"` も付ける）。`items` は**配列を JSON 文字列にしたもの** |
| クイズを作る | `POST /api-2.0/courses/<courseId>/quizzes/` `{title, description, type: "simple-quiz"}` |
| 問題を入れる | `POST /api-2.0/quizzes/<quizId>/assessments/`（本文は `scripts/udemy_quiz_payload.py` が作る） |
| 問題を上書きする | `PUT /api-2.0/quizzes/<quizId>/assessments/<id>/` |

### 2-3. ページ内スクリプトの共通の注意

- **ページを移動すると `window.__*` は消える。** 移動したら定義し直す
- **1回の評価は約 45 秒で切れる。** 長いループは投げっぱなしにし、状態を短い呼び出しで読む（ページの中では最後まで動く）
- 結果を返すときは、Cookie やクエリ文字列を含めない（ツールの出力で塞がれる）。メソッド・パス・状態だけ返す
- 講座 ID は URL（`/course/<id>/`）から取る。スクリプトに埋め込まない

## 3. 動画のアップロード

**Claude in Chrome の `file_upload` は合計 10MB が上限**で、講義の動画（14〜84MB）は通らない。
代わりに、ページ内で「ファイルを選んだ」操作を再現して、Udemy 自身のアップローダを動かす。

1. 置き場を配る：`python scripts/udemy_file_server.py <置き場>`（127.0.0.1:8765。CORS と Private Network Access のヘッダ付き）。
   **置き場は引数で必ず渡す**（作業フォルダーがずれて全部 404 になった）。起動したら `/list/<NN>` で一覧が返るかを確かめる
2. 講義の行の「＋ コンテンツ」→「動画」を開く（下の `__open`）。上げ済みの動画を差し替えるときは、行の ∨ で開いて「コンテンツを編集」
3. ページ内でファイルを取り、入力欄に渡す。**ページの `fetch` は計測スクリプトに包まれて localhost で `Failed to fetch` になることがある → `XMLHttpRequest`（blob）で取る。**
   **状態 200 と大きさを必ず確かめる**（404 の本文 335 バイトを動画として渡し、空の動画が上がった）

```js
window.__up = async (title, nn, idx, name) => {
  const ins = [...document.querySelectorAll('input[type=file]')];
  const el = ins.find(e => { let p = e; for (let k = 0; k < 12 && p; k++) { p = p.parentElement; if (p && p.textContent.includes('レクチャー')) break; }
    return p && p.textContent.includes(title) && (e.parentElement?.textContent || '').includes('ビデオを選択'); });
  if (!el) return 'no input';
  const r = await new Promise((ok, ng) => { const x = new XMLHttpRequest(); x.open('GET', `http://127.0.0.1:8765/f/${nn}/${idx}`);
    x.responseType = 'blob'; x.onload = () => ok(x); x.onerror = () => ng(new Error('xhr')); x.send(); });
  if (r.status !== 200 || r.response.size < 1000000) return 'bad ' + r.status + ' ' + r.response.size;
  const f = new File([r.response], name, {type: 'video/mp4'});
  const dt = new DataTransfer(); dt.items.add(f); el.files = dt.files;
  el.dispatchEvent(new Event('change', {bubbles: true}));
  return r.status + ' ' + f.size;   // 200 と大きさが返れば渡せた
};
window.__open = async (title) => {   // 行の「＋ コンテンツ」→「動画」を、座標を使わずに開く
  const btns = [...document.querySelectorAll('button')].filter(b => b.textContent.trim().endsWith('コンテンツ'));
  let target = null;
  for (const b of btns) { let p = b; for (let k = 0; k < 6 && p; k++) { p = p.parentElement;
    if (p && p.textContent.includes(title)) { if (p.textContent.length < 200) target = b; break; } } if (target) break; }
  if (!target) return 'no button';
  target.scrollIntoView({block: 'center'}); target.click(); await new Promise(r => setTimeout(r, 1200));
  const vids = [...document.querySelectorAll('*')].filter(e => e.children.length === 0 && e.textContent.trim() === '動画' && e.offsetParent !== null);
  if (!vids.length) return 'no video';
  let c = vids[vids.length - 1]; for (let k = 0; k < 4; k++) { if (c.tagName === 'BUTTON' || c.getAttribute('role') === 'button') break; c = c.parentElement; }
  c.click(); await new Promise(r => setTimeout(r, 1500)); return 'opened';
};
```

- 講義ごとに `await __open('講義名'); await __up('講義名', '01', 3, '03_slug.mp4')` を4秒あけて回す（6本で約1分）
- 題名の一致は、行の表示の頭に付く「レクチャー N:」を外してから比べる。既にコンテンツのある行は飛ばす（二重に付けない）
- **速さは回線で決まる。** 約 2 本/分、同時 2 本でも 4 本でも変わらなかった。同時 2 本で十分
- 転送が終わると「処理しています」になり、数分で処理が終わる（asset の status 0 → 1）。差し替え中は、ヘッダーの合計尺が一時的に減る
- **差し替え**は「コンテンツを編集」から同じ `__up` を使う。前の動画を消す操作は要らない。講義を消して作り直さない（受講者の進み具合が消える）。公開状態と外部リソースは保たれる
- 全部の転送が終わったら配信を止める（`Get-NetTCPConnection -LocalPort 8765` で PID を調べ、その PID だけを止める）
- **改名はアップロード完了を待たず、終わった講義から順に行う**（全部が終わるまで番号つきの題名が見えたままになり、制作者に指摘された）

## 4. 記事の講義（ボーナス レクチャー）

- 講義を足す →「＋ コンテンツ」→「記事」→ エディタ右上の「HTMLを編集」→ 原稿から作った HTML（`<p>`・`<ul><li>`・`<a href>`）を `type` で入れる →「ライブプレビュー」で見た目を確かめる →「保存」
- 確かめ: 読み取りで `fields[asset]=asset_type,body` を付けると、`Article` と本文が返る
- **ほかのコースの案内は、ボーナス レクチャーだけに置く**（Udemy の決まり。ボーナス レクチャーはマーケティングの場所で、講義の中で受講者をほかの場所へ誘ってはいけない）
  - **講義名は「ボーナスレクチャー」だけにする。** 「ボーナスレクチャー：次に挑戦する試験」のように中身を示す語を足すと、審査で差し戻される（2026-10-24）
  - **講義の説明欄は空にする**
  - **コースの最後の項目にする。** 講義や小テストを足したら、最後のままかを §6 で確かめる
  - ほかの講義名・説明・コースの説明・メッセージで、ボーナス レクチャーの中身を予告しない
  - 本文には、ほかのコースへのリンクやクーポンを書いてよい

## 5. 小テスト（Udemy のクイズ）

演習テストとは別物。CSV の一括アップロードは無い。原稿の形と作り方の規則は `references/quiz-authoring.md`。

### 5-1. 原稿から入れる文を作る

```
python scripts/udemy_quiz_payload.py --from-md lectures/04_ide/L4-1_quiz.md -o quiz_import.json --qs qs.json
```

- 原稿の `## 問題` の節だけを読む（後ろの「保留案」「参照」の節まで読むと、同じ番号の問題が重複して入る）
- 検証：選択肢 2〜6・正解はちょうど1つ・解説がある。外れた問題があれば何も書き出さない
- `--qs` は画面の操作で入れるための `window.__QS`。書式なしなので `**太字**` と `` `コード` `` の記号を外す
- 選択肢ごとの解説は「正解です。」／「不正解です。」＋解説全文（どれを選んでも理由が読める）
- 正解の位置の偏り（a..f の数）を表示する。偏りが大きければ原稿で入れ替える
- 出典の行と、作り手向けの説明（問いの作り方を述べた文）は入れない

### 5-2. 画面の操作で入れる（既定）

1. セクション下端の「＋ カリキュラム項目」→ メニューを下へスクロール →「小テスト」→ タイトルを入れて「クイズを追加」。説明の欄は空でよい
2. **見返す講義に動画が入ってから問いを入れる。** 「復習用レクチャー」の候補には、動画の付いた講義だけが、**ページを開いた時点のもの**で出る。動画を上げたらページを読み込み直す
3. `templates/udemy_quiz_helpers.js` の中身を `javascript_tool` に渡す（先に `window.__QS`・`window.__T`（小テストの名前）・`window.__lid`（見返す講義の id）を入れる）
4. 流れ: `await __newq(__T, '質問')` → `await __fillq(0)` → `await __submit()` → 2問目からは `__newq(__T, '新しい問題')` → `__fillq(n)` → `__submit()`
   - `__newq` のあとは「フォームが1つ・最初の欄が空」を確かめてから入れる
   - **1回の JS は2問まで。** 4問を1回で回すと 45 秒で結果が返らない（ページの中では最後まで動く。10 秒待って API で確かめる）
   - `__submit` は保存のあと assessments API で、その小テストの問いの数・正解の位置・見返す講義を返す。**画面のフォームが消えたことは、保存できた証拠にならない**

画面の罠は次のとおり（どれも実際に起きた）。
- **「新しい問題」のボタンは、ページに小テストの数だけある（隠れている分も）。** 1つ目を押すと別の小テストのフォームが開く。親を何段かたどって名前を探す書き方では、セクション全体が当たって**別の小テストに3問入った**。「名前を含む一番近い親の中に『新しい問題』が1つだけ」のものを選ぶ（`__newq` はそうしている）
- 1問目のボタンは「＋ 質問」、2問目からは「新しい問題」
- **4つ目の回答欄は、3つ目に入力すると現れる**（`__fillq` は待ってから入れる）。ref で入れるときは read_page を取り直す（ref は毎回ずれる。`find` は古い ref を返すことがある）
- **D の正解のラジオは、ref のクリックで付かないことがある。** JS で `form.querySelectorAll('input[type=radio]')` の checked を読み、外れていたら `rs[i].click()`
- 入力は `focus()` → `execCommand('selectAll')` → `execCommand('insertText', false, 文)`。React が拾い、保存した文が原稿と一字一句同じになる。1文字ずつの `type` より速く確か
- 見返す講義のプルダウンは、`HTMLSelectElement` の value の setter を call してから change を出す（React が拾う）
- **小テストの見出しの行のごみ箱を押さない**（小テストごと消える）

### 5-3. API で入れる（許されている環境だけ）

`quiz_import.json` の各問の `body` を `POST /api-2.0/quizzes/<quizId>/assessments/` で送る。入れた問題の id を記録して、やり直しで二重に入れない。
並び（`PUT …/instructor-curriculum-items/`）で、各まとまりの最後の講義の次に挿す。

- **問題の DELETE は 204 を返しても、一覧の API には数分残る。** 消えたかは問いの個別の GET が 404 になるかで確かめる。試しに入れた問題は、消さずに本物の問題で PUT して上書きするのが確か

## 6. 検証（全数・読み取りだけ）

```js
// 並び・動画の処理（status 1 で処理済み）・尺・公開状態
const cid = location.pathname.match(/course\/(\d+)/)[1];
await (await fetch(`/api-2.0/courses/${cid}/instructor-curriculum-items/?page_size=400&fields[chapter]=title&fields[lecture]=title,description,is_published,is_free,asset&fields[quiz]=title&fields[asset]=asset_type,filename,status,time_estimation,created`, {credentials: 'include'})).json();
// 小テストの正解の位置・見返す講義・文面
await (await fetch(`/api-2.0/quizzes/<quiz_id>/assessments/?page_size=50&fields[assessment]=prompt,correct_response,related_lectures`, {credentials: 'include'})).json();
```

- 並び：セクション・講義・小テストを、講座側の一覧と1件ずつ突き合わせる（件数だけで済ませない）。ボーナス レクチャーが最後か
- 講義名：承認した案と同じか、番号が入っていないか、実践の印があるか
- 動画：全講義に asset が付いているか、`status` が 1 か。処理中の数も報告する
- **公開状態：`is_published` が false の講義が 0 件か。公開済みのコースに新しく足した講義は「未公開」のまま残る**（講義ごとに「公開」を押すまで受講者に見えない。公開ボタンは動画の処理が終わるまで出ない。実践 26 本が約2週間見えず、受講者に指摘された）
- 差し替え：`asset.created` が当日・`time_estimation` が新しい尺・`is_published` が保たれているか
- 小テスト：問いの数・正解の位置・見返す講義が原稿と同じか。`prompt.question`・`answers`・`feedbacks` から `<p>` などの札を外して、原稿の文と同じか。**ほかの小テストの問いの数が変わっていないか**も見る（取り違えて入った例がある）
- 説明欄などの長文は、入力後の innerText を原稿と突き合わせる（原稿に無い語が紛れていた例がある）
- 確かめた結果は、講座側の追跡表と引き継ぎの文書に書く

## 7. 審査に出す前の最終点検

制作者が審査に出す前に、次を読み取りで確かめて報告する（ある講座では、全講義を上げた後もコースの説明が旧い下書きのままだった）。

- **コースの説明・学習目標・前提・対象者が、今の講座の中身と合っているか**（旧い下書きを流用したときは特に）
- **AI の使用の開示**: 台本・図解・音声・画面の操作に AI を使う講座は、説明文の先頭に「本コースにはAIの使用が含まれています。」（審査で求められた定型文。文言を変えない）。続けて「■ AI の使用について」として、企画と確認は講師、台本と図解は AI の支援、ナレーションは合成音声、のように役割を書く
- 説明の「最低 200 語」はロケールで数え方が変わる（英語のロケールでは日本語が 0 語に数えられる。言語を日本語にすると文字数で判定される）
- 説明欄はリッチテキスト（ProseMirror）。箇条書きはツールバーのリストボタンで作る（「・」を打っても箇条書きにならない）
- 審査に出せる条件: 講義 5 本以上・動画 30 分以上（無料講座は動画 2 時間以内）
- 講義と小テストの数・全動画の status・未公開の講義が 0 件か（§6）
- ボーナス レクチャーの決まり（§4）
- **無料プレビュー**: プレビューの動画が合わせて 10 分に足りないと、カリキュラムの画面に警告が出る（そのままなら Udemy が別の動画を1本、自動でプレビューにする）。どれをプレビューにするかは制作者に聞く
- 字幕の方針（講座で決める。既定は上げず、Udemy の自動字幕に任せる。上げる場合は §10）
- 価格は制作者が決める

## 8. 審査の結果に対応する

- 結果は「コースの審査結果」（`/instructor/course/<id>/manage/feedback/`）に出る。**要修正**（直さないと再提出できない）と**推奨改善項目**（任意）に分かれる
- 指摘を直したら、読み取りで直ったことと、ほかの場所に同じ問題が無いことを確かめる
- 返信は、文面を制作者に見せて了解を得てから送る。項目ごとのコメント欄は **Enter で投稿**される（改行は Shift+Enter）。**投稿すると、その項目は自動で「修正済み」になる**
- 推奨改善項目には、返信も「修正済み」の印も、制作者の指示なしに付けない
- **AI の音声を使う講座には、推奨改善項目「音質」が付く**（基準は満たしているが、「声がロボットのよう」「明らかな発音の誤り」などの報告があれば再審査の対象になり得る、という注意）。読みの誤りを減らす工程（`references/tts-readings.md`）が、そのまま備えになる
- **「審査に再提出」は制作者が押す**
- 指摘の中身は、Udemy 一般の決まりとして講座の教訓ファイルとこのスキルに足す（次の講座で同じ差し戻しを受けない）

## 9. 差し替え・削除（公開後を含む）

- 動画を直したら、その講義のコンテンツを置き換える（§3。講義を消して作り直さない）
- 小テストの問題は、編集のフォームか PUT で上書きする
- **公開後の変更は制作者の指示があるときだけ行う**
- 消すものは一覧にして制作者に頼み、消えたかを §6 の読み取りで確かめる。講義を先に、セクションは後に（セクションを消しても中の講義は残る）

## 10. 参考: 字幕を上げる場合

- Udemy の字幕は WebVTT だけを受け付ける（.srt は変換する）
- `file_upload` で渡したファイルは種類が空になり、署名 API（`s3-upload-signatures`）が 400 を返す。字幕のページを開いたら、先にページ内で `Blob.prototype.type` の getter を「名前が .vtt なら text/vtt を返す」ように差し替えてから渡す（ページを読み込み直すと元に戻る）

## 関連

- 上流：`make-slide-lecture`（Hyperframes のスライド型。座学と実践の本体。次の版で追加）・`make-lecture-movie`／`make-practice-movie`（旧経路）
- コースの基本情報・画像・長文の入れ方：`udemy-exam-prep` の `create-udemy-course`
- 演習テスト（practice test）：`udemy-exam-prep` の `udemy-bulk-upload` / `upload-practice-tests`
- 小テストの作り方：`references/quiz-authoring.md`。補助関数：`templates/udemy_quiz_helpers.js`
- ブラウザと長い処理の運用：`references/windows-and-ops.md`
- 教訓の置き場：`references/self-improvement.md`（Udemy の操作で踏んだことは「Udemy 一般」として講座の教訓ファイルに書く）
