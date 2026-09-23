/* Udemy 演習テストの編集画面（.../manage/practice-test/?quizId=...）用ヘルパー。
 * 使い方: sync_server.py を起動し、編集画面で
 *   eval(await (await fetch('http://127.0.0.1:8765/editor-helper.js')).text());
 *   await __u.load(<セクション番号>);   // 問題データと旧版の署名を取得
 *   __u.visible();                      // 'visible' でなければタブを前面に出してもらう（hidden だとタイマーが絞られ止まる）
 *   __u.runBg([問題番号, ...]);         // 基本はこれ。1問につき最大 tries(=3) 回試行。__u.jobStatus() で進捗を確認
 *   __u.stop();                         // 実行中のジョブ（runBg / auditBg）を次の問題の手前で止める
 *   __u.fast = true;                    // 初回試行だけ保存後の往復検証を省く（約2倍速）。必ず最後に audit で全問を照合する
 *   __u.auditBg(1, 50);                 // 保存内容を CSV と照合（バックグラウンド）。__u.auditStatus() の mismatch が空なら一致
 *   await __u.audit(1, 15);             // 同期版の照合。1回の JS 実行が45秒を超えないよう 15 問程度まで
 *   await __u.runAll([問題番号, ...]);  // 同期版。通常モードでは1問でも45秒を超えることがあるので runBg を使う
 *   __u.runBg([問題番号, ...], 'link'); // 本文はそのままで、素の URL だけをリンクに変える（一括アップロード直後に使う）
 *   __u.links = false;                  // run 時の URL リンク化を止める（既定は true）
 * 入力は execCommand('insertText')（type アクションは文字が欠落・置換・入れ替わる）。
 * URL のリンク化は execCommand('insertHTML') で <a href target="_blank"> を差し込む。innerText は変わらないので署名照合と両立する。
 * 一括アップロード（CSV）の URL は素のテキストとして保存され、受講者はクリックできない（実測: <p>出典: https://...</p>）。
 * ページを再読み込みすると __u・データ・ジョブ状態は消える。読み込みからやり直す。
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
  links:true,
  // 素の URL（<a> の外にあるもの）。末尾の句読点・閉じ括弧は URL に含めない
  _urlRe(){return /https?:\/\/[^\s<>"'、。，．（）「」【】]+/g;},
  _trimUrl(u){return u.replace(/[.,;:!?)\]}]+$/,'');},
  _bare(e){const out=[];const w=document.createTreeWalker(e,NodeFilter.SHOW_TEXT);let n;
    while((n=w.nextNode())){if(n.parentElement&&n.parentElement.closest('a'))continue;const re=this._urlRe();let m;
      while((m=re.exec(n.textContent))){const u=this._trimUrl(m[0]);if(u.length>8)out.push({node:n,idx:m.index,url:u});}}
    return out;},
  unlinked(e){return this._bare(e).length;},
  linkify(e){let n=0;for(let guard=0;guard<50;guard++){const b=this._bare(e)[0];if(!b)break;
      e.focus();const r=document.createRange();r.setStart(b.node,b.idx);r.setEnd(b.node,b.idx+b.url.length);
      const s=window.getSelection();s.removeAllRanges();s.addRange(r);
      document.execCommand('insertHTML',false,'<a href="'+b.url+'" target="_blank" rel="noopener noreferrer">'+b.url+'</a>');n++;}
    return n;},
  linkifyAll(){let n=0;for(const e of this.eds())n+=this.linkify(e);return n;},
  // 本文には触れず、URL だけをリンクにして保存する（一括アップロード後の仕上げ用）
  async linkifyOne(q){if(!(await this.goto(q)))return JSON.stringify({q:q,abort:'align',head:(this.eds()[0]?.innerText||'').slice(0,20)});
    const before=JSON.parse(this.sig());const n=this.linkifyAll();
    if(!n)return JSON.stringify({q:q,ok:true,linked:0});
    if(JSON.stringify(JSON.parse(this.sig()))!==JSON.stringify(before))return JSON.stringify({q:q,abort:'linktext'});
    await this.sleep(200);this.save();await this.sleep(2800);this.dismiss();
    const left=this.eds().reduce((a,e)=>a+this.unlinked(e),0);
    return JSON.stringify(left?{q:q,ok:false,abort:'unlinked',left:left}:{q:q,ok:true,linked:n});},
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
    if(this.links){this.linkifyAll();await new Promise(r=>setTimeout(r,200));}
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
  tries:3,
  retryWait:2500,
  sleep(ms){return new Promise(r=>setTimeout(r,ms));},
  visible(){return (typeof document!=='undefined'&&document.visibilityState)||'unknown';},
  _hidden(job,q){if(this.visible()==='hidden'){const l=job.hidden;if(!l.length||l[l.length-1].q!==q)l.push({q:q,at:new Date().toISOString()});return true;}return false;},
  _watch(){if(this._watching||typeof document==='undefined'||!document.addEventListener)return;this._watching=true;
    document.addEventListener('visibilitychange',()=>{if(document.visibilityState!=='hidden')return;
      for(const j of [window.__job,window.__audit])if(j&&j.running)j.hidden.push({q:j.cur,at:new Date().toISOString(),ev:'visibilitychange'});});},
  stop(){let n=0;for(const j of [window.__job,window.__audit])if(j&&j.running){j.stopReq=true;n++;}return n?'stopping':'idle';},
  runBg(list,mode){if(window.__job&&window.__job.running)return 'busy';
    const fn=mode==='link'?'linkifyOne':'run';
    const base=!!this.fast;const job=window.__job={total:list.length,done:0,running:true,stopped:null,stopReq:false,cur:null,results:[],retries:0,log:[],hidden:[]};
    this._watch();
    (async()=>{try{for(const q of list){
        if(job.stopReq){job.stopped={q:q,abort:'stop'};break;}
        job.cur=q;this._hidden(job,q);let r=null;
        for(let t=0;t<this.tries;t++){
          this.fast=t===0?base:false;this.dismiss();
          try{r=JSON.parse(await this[fn](q));}catch(e){r={q:q,abort:'exc',e:String(e)};}
          if(r.ok&&!r.abort)break;
          job.log.push(Object.assign({try:t+1,hidden:this.visible()==='hidden'},r));
          if(t+1<this.tries){job.retries++;await this.sleep(this.retryWait);}}
        job.results.push(r);job.done++;
        if(!r.ok||r.abort){job.stopped=r;break;}}}
      finally{this.fast=base;job.running=false;job.cur=null;}})();
    return 'started '+list.length;},
  jobStatus(){const j=window.__job||{};return JSON.stringify({total:j.total,done:j.done,running:j.running,stopped:j.stopped,retries:j.retries,
    log:(j.log||[]).slice(-5),hidden:j.hidden,visible:this.visible()});},
  async runAll(list){const out=[];for(const q of list){let r;try{r=JSON.parse(await this.run(q));}catch(e){r={q:q,abort:'exc',e:String(e)};}
    out.push(r);if(r.abort||!r.ok)break;}return JSON.stringify(out);},
  async auditOne(q){const g=await this.goto(q);
    const got=JSON.parse(this.sig());const d=window.__d[String(q)];
    const okAll=JSON.stringify(got)===JSON.stringify(d.sig);
    const cor=this.tog().map((c,i)=>c.checked?i+1:0).filter(Boolean);
    const unl=this.links?this.eds().reduce((a,e)=>a+this.unlinked(e),0):0;
    return {q:q,nav:g,sig:okAll,cor:JSON.stringify(cor)===JSON.stringify(d.correct),ty:(this.tog()[0]?.type==='checkbox')===(d.type==='multi-select'),unlinked:unl};},
  // unlinked: リンクになっていない素の URL の数（links=false なら数えない）
  bad(x){return !x.sig||!x.cor||!x.ty||!x.nav||(x.unlinked||0)>0;},
  async audit(a,b){const out=[];for(let q=a;q<=b;q++){let x;try{x=await this.auditOne(q);}catch(e){x={q:q,err:String(e)};}
    if(x.err||this.bad(x))out.push(x);}
    return JSON.stringify(out);},
  auditBg(a,b){if(window.__audit&&window.__audit.running)return 'busy';
    const job=window.__audit={a:a,b:b,at:null,cur:null,running:true,done:false,stopReq:false,res:[],err:[],hidden:[]};
    this._watch();
    (async()=>{try{for(let q=a;q<=b;q++){
        if(job.stopReq)break;
        job.cur=q;this._hidden(job,q);
        try{const x=await this.auditOne(q);if(this.bad(x))job.res.push(x);}catch(e){job.err.push({q:q,e:String(e)});}
        job.at=q;}
      job.done=job.at===b;}
      finally{job.running=false;job.cur=null;}})();
    return 'started '+a+'-'+b;},
  auditStatus(){const j=window.__audit||{};return JSON.stringify({a:j.a,b:j.b,at:j.at,running:j.running,done:j.done,mismatch:j.res,err:j.err,hidden:j.hidden,visible:this.visible()});}
};
