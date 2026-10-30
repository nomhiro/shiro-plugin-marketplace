// Udemy の動画講座の小テストを、画面の操作でまとめて入れる補助関数（publish-video-course §4）。
// ハンズオン中心の講座（2026-10-22）で使った補助関数を、講座 ID を URL から取る形にしたもの。
// 使い方: カリキュラムの画面（/instructor/course/<id>/manage/curriculum/）で、先に次を入れてから、この中身を
// javascript_tool にそのまま渡す。最後の式が [小テストの id, 問いの数] を返す。
//   window.__QS  = scripts/udemy_quiz_payload.py --qs が書き出した、その小テストの配列
//   window.__T   = 小テストの名前（画面の表示と同じ文字列）
//   window.__lid = 見返す講義の id（curriculum-items API で名前から引く。動画の付いた講義だけが候補に出る）
// 講座 ID は URL から取る（/course/<id>/）。
// 流れ: await __newq(__T, '質問') → await __fillq(0) → await __submit() → 2問目から __newq(__T, '新しい問題') → __fillq(n) → __submit()。
// 1回の JS は2問まで（45 秒で結果が返らなくなる。ページの中では最後まで動くので、そのときは API で確かめる）。
const __cid = (location.pathname.match(/course\/(\d+)/) || [])[1];
const c = await (await fetch('/api-2.0/courses/' + __cid + '/instructor-curriculum-items/?page_size=200&fields[quiz]=title&fields[lecture]=title&_=' + Date.now(), {credentials: 'include', cache: 'no-store'})).json();
window.__qid = c.results.find(x => x._class === 'quiz' && x.title === window.__T).id;
window.__newq = async (title, label) => {
  const btns = [...document.querySelectorAll('button')].filter(b => b.textContent.trim().replace(/^[＋+]\s*/, '') === label);
  let target = null;
  for (const b of btns) { let p = b; while (p && !p.textContent.includes(title)) p = p.parentElement;
    if (p && [...p.querySelectorAll('button')].filter(x => x.textContent.trim().replace(/^[＋+]\s*/, '') === label).length === 1) { target = b; break; } }
  if (!target) return 'no button';
  target.scrollIntoView({block: 'center'}); target.click(); await new Promise(r => setTimeout(r, 1000));
  const mc = [...document.querySelectorAll('button')].filter(b => b.textContent.trim() === '選択式' && b.offsetParent !== null);
  if (mc.length !== 1) return 'mc=' + mc.length; mc[0].click(); await new Promise(r => setTimeout(r, 1500)); return 'ok'; };
window.__qform = () => [...document.querySelectorAll('form')].filter(f => { let p = f; while (p && !p.textContent.includes(window.__T)) p = p.parentElement;
    return p && [...p.querySelectorAll('button')].filter(x => x.textContent.trim() === '新しい問題').length <= 1 && f.querySelectorAll('input[type=radio]').length; });
window.__fields = () => { const fs = window.__qform(); if (fs.length !== 1) return []; return [...fs[0].querySelectorAll('[contenteditable=true], textarea, input[type=text]')]; };
window.__setlec = (lid) => { const s = window.__qform()[0].querySelector('select'); Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value').set.call(s, lid); s.dispatchEvent(new Event('change', {bubbles: true})); s.dispatchEvent(new Event('input', {bubbles: true})); return s.value; };
window.__fillone = async (i, text) => { const e = window.__fields()[i]; if (!e) return 'none ' + i;
  e.scrollIntoView({block: 'center'}); e.focus(); document.execCommand('selectAll');
  const ok = document.execCommand('insertText', false, text); await new Promise(r => setTimeout(r, 400));
  return ok + ':' + ((e.value ?? e.textContent) === text); };
window.__fillq = async (n) => { const q = window.__QS[n]; const t = [q.s]; const res = [];
  for (let k = 0; k < 4; k++) t.push(q.o[k], (k === q.a ? '正解です。' : '不正解です。') + q.e);
  for (let i = 0; i < 9; i++) { if (i === 7) await new Promise(r => setTimeout(r, 800)); res.push(await window.__fillone(i, t[i])); }
  window.__qform()[0].querySelectorAll('input[type=radio]')[q.a].click(); res.push(window.__setlec(window.__lid)); return res.join(' '); };
window.__submit = async () => { const fs = window.__qform(); if (fs.length !== 1) return 'forms=' + fs.length;
  [...fs[0].querySelectorAll('button')].find(x => x.textContent.trim() === '保存').click(); await new Promise(r => setTimeout(r, 3000));
  const a = await (await fetch('/api-2.0/quizzes/' + window.__qid + '/assessments/?page_size=50&fields[assessment]=correct_response,related_lectures&_=' + Date.now(), {credentials: 'include', cache: 'no-store'})).json();
  return a.results.map(x => [x.correct_response[0], (x.related_lectures || []).map(l => l.id)[0]]); };
[window.__qid, window.__QS.length]
