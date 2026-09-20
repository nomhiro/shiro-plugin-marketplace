/* Udemy 演習テストの編集画面（.../manage/practice-test/?quizId=...）用ヘルパー。
 * 使い方: sync_server.py を起動し、編集画面で
 *   eval(await (await fetch('http://127.0.0.1:8765/editor-helper.js')).text());
 *   await __u.load(<セクション番号>);   // 問題データと旧版の署名を取得
 *   await __u.runAll([問題番号, ...]);  // 4問ずつ（1問≈8秒。CDP は45秒でタイムアウト）
 *   __u.runBg([問題番号, ...]);         // 多数の問題はバックグラウンドで。__u.jobStatus() で進捗を確認
 *   __u.fast = true;                    // 保存後の往復検証を省く（約2倍速）。必ず最後に audit で全問を照合する
 *   await __u.audit(1, 17);             // 保存内容を CSV と照合。空配列なら一致
 * 入力は execCommand('insertText')（type アクションは文字が欠落・置換・入れ替わる）。
 */
window.__BASE = window.__BASE || 'http://127.0.0.1:8765';
window.__u={
  items(){return [...document.querySelectorAll('[class*="left-area--item--"]')];},
  pick(n){const e=this.items()[n];const t=e.querySelector('[class*="item-wrapper"]')||e;
    for(const ty of ['pointerdown','mousedown','pointerup','mouseup','click'])
      t.dispatchEvent(new MouseEvent(ty,{bubbles:true,cancelable:true,view:window}));
    return e.innerText.trim().slice(0,24);},
  eds(){return [...document.querySelectorAll('[contenteditable="true"]')];},
  tog(){return [...document.querySelectorAll('[class*="answer--answer-toggle--"] input')];},
  btn(l){return [...document.querySelectorAll('button')].find(b=>b.innerText.trim()===l);},
  addOpt(k){for(let j=0;j<k;j++)this.btn('回答の選択肢を追加').click();return this.eds().length;},
  setType(t){const b=this.btn(t);if(b)b.click();return t;},
  setText(i,text){const e=this.eds()[i];e.scrollIntoView({block:'center'});e.focus();
    const r=document.createRange();r.selectNodeContents(e);
    const s=window.getSelection();s.removeAllRanges();s.addRange(r);
    document.execCommand('insertText',false,text);return this.h(this.eds()[i].innerText);},
  setCorrect(a){const t=this.tog();let n=0;t.forEach((c,i)=>{const w=a.includes(i+1);if(c.checked!==w){c.click();n++;}});
    return JSON.stringify({clicked:n,now:this.tog().map(c=>c.checked)});},
  setDomain(name){const r=[...document.querySelectorAll('input[type="radio"]')].filter(x=>!x.closest('[class*="answer--answer-toggle--"]'));
    const t=r.find(x=>((x.closest('[class*="item"]')||x.parentElement.parentElement).innerText||'').trim().startsWith(name));
    if(t&&!t.checked)t.click();return r.map(x=>x.checked);},
  save(){this.btn('質問を保存').click();return 'saved';},
  h(s){s=(s||'').replace(/\u00a0/g,' ').replace(/\r/g,'').replace(/\n+/g,'\n').trim();
    let h=5381;for(let i=0;i<s.length;i++){h=((h*33)^s.charCodeAt(i))>>>0;}return s.length+':'+h;},
  sig(){return JSON.stringify(this.eds().map(e=>this.h(e.innerText)));},
  state(){return JSON.stringify({q:this.eds()[0]?.innerText.slice(0,24),n:this.eds().length,tog:this.tog().map(c=>c.checked),ty:this.tog()[0]?.type});},
  async load(sec){window.__sec=sec;
    window.__d=await (await fetch(window.__BASE+'/data/s'+sec+'.json')).json();
    window.__o=await (await fetch(window.__BASE+'/data/o'+sec+'.json')).json();
    return [this.items().length,Object.keys(window.__d).length];},
  async check(list){const out=[];for(const q of list){await this.goto(q);
    const cur=this.h(this.eds()[0]?.innerText||'');const o=window.__o[String(q)],n=window.__d[String(q)];
    out.push({q:q,old:cur===o.q0,already:cur===n.sig[0],ty:this.tog()[0]?.type,nf:this.eds().length,want:n.f.length,wt:n.type,head:(this.eds()[0]?.innerText||'').slice(0,14)});}
    return JSON.stringify(out);},
  dismiss(){const m=[...document.querySelectorAll('[role="dialog"]')].find(e=>e.innerText.includes('保存されていません'));
    if(!m)return 0;const x=[...m.querySelectorAll('button')].find(b=>!b.innerText.trim());if(x)x.click();return 1;},
  side(q){return (this.items()[q]?.innerText||'').trim().replace(/^\d+\.\s*/,'').replace(/\s+/g,' ');},
  persisted(q){const d=window.__d[String(q)];const want=d.f[0].replace(/\s+/g,' ').slice(0,12);return this.side(q).startsWith(want);},
  async goto(q){this.dismiss();const o=window.__o[String(q)],d=window.__d[String(q)];
    for(let t=0;t<4;t++){this.pick(q);await new Promise(r=>setTimeout(r,t?1200:1600));
      const cur=this.h(this.eds()[0]?.innerText||'');
      if(cur===o.q0||cur===d.sig[0])return true;}
    return false;},
  async run(q,nxt){const d=window.__d[String(q)],o=window.__o[String(q)];if(!d)return JSON.stringify({abort:'nodata'});
    if(!(await this.goto(q)))return JSON.stringify({q:q,abort:'align',head:(this.eds()[0]?.innerText||'').slice(0,20)});
    const hasOv=!document.querySelector('[data-purpose="add-overall-explanation"]');
    let m=this.tog().length;
    while(m<d.n){const ab=this.btn('回答の選択肢を追加');if(!ab)break;ab.click();await new Promise(r=>setTimeout(r,600));m=this.tog().length;}
    if(!hasOv){const b=document.querySelector('[data-purpose="add-overall-explanation"]');if(b)b.click();await new Promise(r=>setTimeout(r,600));}
    if(this.eds().length!==d.f.length)return JSON.stringify({q:q,abort:'fieldcount',have:this.eds().length,want:d.f.length,nopt:this.tog().length,wantn:d.n,ty:this.tog()[0]?.type,wantty:d.type});
    if((this.tog()[0]?.type==='checkbox')!==(d.type==='multi-select'))return JSON.stringify({q:q,abort:'type',have:this.tog()[0]?.type,want:d.type});
    for(let i=0;i<d.f.length;i++){this.setText(i,d.f[i]);await new Promise(r=>setTimeout(r,110));}
    this.setCorrect(d.correct);
    if(d.domain)this.setDomain(d.domain);
    const got=JSON.parse(this.sig());
    const bad=got.map((g,i)=>g===d.sig[i]?null:i).filter(x=>x!==null);
    if(bad.length)return JSON.stringify({q:q,abort:'sig',bad:bad,got:bad.map(i=>got[i]),exp:bad.map(i=>d.sig[i])});
    this.save();await new Promise(r=>setTimeout(r,this.fast?2000:2800));
    this.dismiss();
    if(this.fast)return JSON.stringify({q:q,ok:true,fast:true});   // 往復検証は省く。最後に audit で照合する
    this.pick(q===1?2:1);await new Promise(r=>setTimeout(r,1300));this.dismiss();
    const nav=await this.goto(q);
    const now=JSON.parse(this.sig());
    const ok=nav&&JSON.stringify(now)===JSON.stringify(d.sig)&&JSON.stringify(this.tog().map((c,i)=>c.checked?i+1:0).filter(Boolean))===JSON.stringify(d.correct);
    return JSON.stringify(ok?{q:q,ok:true}:{q:q,ok:false,abort:'verify',nav:nav,bad:now.map((g,i)=>g===d.sig[i]?null:i).filter(x=>x!==null),tog:this.tog().map(c=>c.checked)});},
  runBg(list){window.__job={total:list.length,done:0,running:true,stopped:null,results:[]};
    (async()=>{for(const q of list){const r=JSON.parse(await this.run(q));window.__job.results.push(r);window.__job.done++;
      if(r.abort||!r.ok){window.__job.stopped=r;break;}}window.__job.running=false;})();
    return 'started '+list.length;},
  jobStatus(){const j=window.__job||{};return JSON.stringify({total:j.total,done:j.done,running:j.running,stopped:j.stopped});},
  async runAll(list){const out=[];for(const q of list){const r=JSON.parse(await this.run(q));out.push(r);if(r.abort||!r.ok)break;}return JSON.stringify(out);},
  async audit(a,b){const out=[];for(let q=a;q<=b;q++){const g=await this.goto(q);
    const got=JSON.parse(this.sig());const d=window.__d[String(q)];
    const okAll=JSON.stringify(got)===JSON.stringify(d.sig);
    const cor=this.tog().map((c,i)=>c.checked?i+1:0).filter(Boolean);
    out.push({q:q,nav:g,sig:okAll,cor:JSON.stringify(cor)===JSON.stringify(d.correct),ty:(this.tog()[0]?.type==='checkbox')===(d.type==='multi-select')});}
    return JSON.stringify(out.filter(x=>!x.sig||!x.cor||!x.ty||!x.nav));}
};
