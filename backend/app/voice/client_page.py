"""Self-contained browser voice client served by FastAPI (works on laptop, phone and tablet browsers).

ChatGPT-style screen: one large speaker orb in the middle. Tapping it opens a customer picker, then starts the
call. Served same-origin so the WebSocket URL is derived from the page address. Browsers only allow microphone
access on HTTPS or http://localhost - the page detects this and explains what to do.

Query parameters:  ?customer_id=CUS1001  (skip the picker)   |   /client/{conversation_id}  (resume a call)
"""
from __future__ import annotations

PAGE = r'''<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Voice Support</title>
<style>
:root{color-scheme:dark;--bg:#212121;--panel:#2a2a2a;--panel2:#303030;--fg:#ececec;--mut:#9b9b9b;--bd:#3a3a3a;--acc:#10a37f;--bad:#ef4444;--user:#2f2f2f;--orb1:#8be9ff;--orb2:#4d7cff;--orb3:#8b3cff}
@media (prefers-color-scheme:light){:root{color-scheme:light;--bg:#ffffff;--panel:#f7f7f8;--panel2:#ececf1;--fg:#202123;--mut:#6e6e80;--bd:#e5e5e5;--user:#f0f0f3}}
*{box-sizing:border-box}html,body{height:100%}
body{margin:0;font:16px/1.55 ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;background:var(--bg);color:var(--fg);display:flex;flex-direction:column;padding:env(safe-area-inset-top) 0 env(safe-area-inset-bottom)}
button,input{font:inherit;color:inherit}
header{display:flex;align-items:center;gap:10px;padding:10px 16px;min-height:52px}
.brand{font-weight:600;letter-spacing:.2px;display:flex;align-items:center;gap:8px}
.brand i{width:22px;height:22px;border-radius:50%;background:linear-gradient(135deg,var(--orb1),var(--orb3));display:inline-block}
.sp{flex:1}
.pill{display:none;align-items:center;gap:8px;padding:5px 12px;border:1px solid var(--bd);border-radius:99px;background:var(--panel);font-size:14px}
.pill.show{display:inline-flex}.pill b{font-weight:600}.pill small{color:var(--mut)}
.ghost{background:transparent;border:1px solid var(--bd);border-radius:10px;padding:6px 12px;cursor:pointer;font-size:14px}
.ghost:hover{background:var(--panel)}.ghost.danger{border-color:var(--bad);color:var(--bad)}.ghost[hidden]{display:none}
#warn{display:none;margin:0 16px;padding:10px 14px;border-radius:12px;background:#3b2f12;color:#ffd58a;font-size:14px}
main{flex:1;min-height:0;display:flex;flex-direction:column;align-items:center}
.stage{display:flex;flex-direction:column;align-items:center;justify-content:center;gap:14px;padding:18px 16px 8px;text-align:center;transition:flex .3s}
main.empty .stage{flex:1}
h1{font-size:28px;font-weight:600;margin:0}
.sub{color:var(--mut);margin:0;font-size:15px;max-width:440px}
/* ---------- the orb ---------- */
.orb-wrap{position:relative;width:210px;height:210px;display:grid;place-items:center;margin:6px 0}
.ring{position:absolute;inset:0;border-radius:50%;border:2px solid var(--orb2);opacity:0;pointer-events:none}
#orb{position:relative;width:170px;height:170px;border-radius:50%;border:0;cursor:pointer;display:grid;place-items:center;color:#fff;
  background:radial-gradient(circle at 30% 28%,var(--orb1),var(--orb2) 55%,var(--orb3));
  box-shadow:0 0 60px rgba(77,124,255,.45),inset 0 -8px 24px rgba(0,0,0,.25);transition:transform .15s ease,filter .3s;
  transform:scale(calc(1 + var(--lvl,0)*.12))}
#orb:hover{filter:brightness(1.08)}#orb:active{transform:scale(.97)}#orb:focus-visible{outline:3px solid var(--acc);outline-offset:6px}
#orb svg{width:72px;height:72px}
#orb .w1,#orb .w2{transform-origin:center;opacity:.9}
.orb-wrap[data-state=idle] #orb{animation:breathe 3.6s ease-in-out infinite}
.orb-wrap[data-state=connecting] #orb{animation:breathe 1s ease-in-out infinite}
.orb-wrap[data-state=listening] .ring{animation:ripple 2.2s ease-out infinite;border-color:#34d399}
.orb-wrap[data-state=listening] .ring.r2{animation-delay:1.1s}
.orb-wrap[data-state=thinking] #orb::after{content:"";position:absolute;inset:-12px;border-radius:50%;border:3px solid transparent;border-top-color:var(--orb1);border-right-color:var(--orb3);animation:spin 1s linear infinite}
.orb-wrap[data-state=speaking] .ring{animation:ripple 1.2s ease-out infinite}
.orb-wrap[data-state=speaking] .ring.r2{animation-delay:.4s}.orb-wrap[data-state=speaking] .ring.r3{animation-delay:.8s}
.orb-wrap[data-state=speaking] .w1{animation:wave .6s ease-in-out infinite alternate}.orb-wrap[data-state=speaking] .w2{animation:wave .6s .2s ease-in-out infinite alternate}
.orb-wrap[data-state=muted] #orb{background:radial-gradient(circle at 30% 28%,#9aa0a6,#5f6368 60%,#3c4043);box-shadow:none}
@keyframes breathe{0%,100%{box-shadow:0 0 40px rgba(77,124,255,.35)}50%{box-shadow:0 0 80px rgba(139,60,255,.55)}}
@keyframes ripple{0%{transform:scale(.8);opacity:.7}100%{transform:scale(1.35);opacity:0}}
@keyframes spin{to{transform:rotate(360deg)}}
@keyframes wave{from{transform:scaleY(.6);opacity:.5}to{transform:scaleY(1.15);opacity:1}}
.status{min-height:24px;font-size:15px;color:var(--mut)}
.chips{display:flex;flex-wrap:wrap;gap:8px;justify-content:center;max-width:560px}
.chips button{background:var(--panel);border:1px solid var(--bd);border-radius:99px;padding:6px 14px;cursor:pointer;font-size:14px}
.chips button:hover{background:var(--panel2)}
/* ---------- conversation ---------- */
#log{flex:1;min-height:0;width:100%;max-width:760px;overflow-y:auto;padding:8px 16px 4px;display:flex;flex-direction:column;gap:18px}
main.empty #log{display:none}
.msg{display:flex;gap:12px;align-items:flex-start}
.msg.user{justify-content:flex-end}
.av{flex:none;width:28px;height:28px;border-radius:50%;background:linear-gradient(135deg,var(--orb1),var(--orb3))}
.msg.user .bub{background:var(--user);border-radius:18px;padding:8px 14px;max-width:80%}
.msg.agent .bub{max-width:calc(100% - 40px)}
.bub{white-space:pre-wrap;word-wrap:break-word}
.sys{align-self:center;color:var(--mut);font-size:13px}
/* ---------- composer ---------- */
#pa{display:none;width:calc(100% - 32px);max-width:728px;margin:6px 0;padding:12px 14px;border:1px solid var(--acc);border-radius:14px;background:var(--panel)}
#pa .t{font-size:13px;color:var(--acc);font-weight:600;margin-bottom:2px}
#pa .row{display:flex;gap:8px;margin-top:10px}
.btn{border:0;border-radius:10px;padding:8px 16px;cursor:pointer;font-weight:600}.btn.ok{background:var(--acc);color:#fff}.btn.no{background:var(--panel2)}
form.bar{width:calc(100% - 32px);max-width:728px;margin:6px 0 14px;display:flex;align-items:center;gap:8px;background:var(--panel);border:1px solid var(--bd);border-radius:28px;padding:6px 8px 6px 18px}
form.bar input{flex:1;min-width:0;background:transparent;border:0;outline:0;padding:8px 0}
form.bar button{width:36px;height:36px;border-radius:50%;border:0;background:var(--fg);color:var(--bg);cursor:pointer;font-size:18px;line-height:1}
form.bar button:disabled{opacity:.3;cursor:default}
.foot{font-size:12px;color:var(--mut);margin-bottom:8px}
/* ---------- customer picker ---------- */
#dlg{position:fixed;inset:0;background:rgba(0,0,0,.6);display:none;align-items:center;justify-content:center;padding:16px;z-index:20}
#dlg.open{display:flex}
.card{width:100%;max-width:460px;max-height:84vh;display:flex;flex-direction:column;background:var(--panel);border:1px solid var(--bd);border-radius:18px;overflow:hidden}
.card h2{margin:0;padding:18px 20px 4px;font-size:20px}.card p{margin:0;padding:0 20px 10px;color:var(--mut);font-size:14px}
.card input{margin:0 16px 8px;padding:10px 14px;border-radius:12px;border:1px solid var(--bd);background:var(--bg);outline:0}
#list{overflow-y:auto;padding:0 8px 8px}
.row2{display:flex;align-items:center;gap:12px;width:100%;text-align:left;background:transparent;border:0;border-radius:12px;padding:10px 12px;cursor:pointer}
.row2:hover:not(:disabled){background:var(--panel2)}.row2:disabled{opacity:.45;cursor:not-allowed}
.ini{flex:none;width:38px;height:38px;border-radius:50%;display:grid;place-items:center;font-weight:600;background:var(--panel2)}
.row2 .n{font-weight:600}.row2 .m{font-size:13px;color:var(--mut)}
.tag{margin-left:auto;font-size:12px;border:1px solid var(--bd);border-radius:99px;padding:2px 8px;color:var(--mut)}
.cardfoot{display:flex;justify-content:flex-end;padding:10px 14px;border-top:1px solid var(--bd)}
</style></head>
<body>
<header>
  <div class="brand"><i></i>Voice Support</div>
  <span id="cust" class="pill"><b id="cname"></b><small id="cid"></small></span>
  <span class="sp"></span>
  <button class="ghost" id="switch" hidden>Switch customer</button>
  <button class="ghost danger" id="end" hidden>End call</button>
</header>
<div id="warn"></div>
<main id="main" class="empty">
  <section class="stage">
    <h1 id="title">How can I help you today?</h1>
    <p class="sub" id="subtitle">Tap the speaker, choose a customer, and just start talking.</p>
    <div class="orb-wrap" id="ow" data-state="idle">
      <span class="ring"></span><span class="ring r2"></span><span class="ring r3"></span>
      <button id="orb" aria-label="Start voice assistant">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
          <path d="M11 5 6 9H3v6h3l5 4V5z" fill="currentColor" stroke="none"/>
          <path class="w1" d="M15.5 8.5a5 5 0 0 1 0 7"/><path class="w2" d="M18.5 5.5a9 9 0 0 1 0 13"/>
        </svg>
      </button>
    </div>
    <div class="status" id="status">Tap the speaker to start</div>
    <div class="chips" id="langs" style="display:none"></div>
  </section>
  <div id="log" role="log" aria-live="polite"></div>
  <div id="pa"><div class="t">Waiting for your confirmation</div><div id="pa-text"></div>
    <div class="row"><button class="btn ok" id="pa-yes">Confirm</button><button class="btn no" id="pa-no">Cancel</button></div></div>
  <form class="bar" id="form"><input id="txt" placeholder="Message… (or just speak)" autocomplete="off" disabled><button id="send" disabled aria-label="Send">&#8593;</button></form>
  <div class="foot">Say “yes” to confirm an action, or use the buttons. Works with any microphone.</div>
</main>

<div id="dlg"><div class="card" role="dialog" aria-modal="true" aria-label="Choose customer">
  <h2>Who is calling?</h2><p>Select the customer for this support call.</p>
  <input id="q" placeholder="Search name, ID, mobile or city" autocomplete="off">
  <div id="list"></div>
  <div class="cardfoot"><button class="ghost" id="cancelpick">Cancel</button></div>
</div></div>

<script>
(() => {
const $ = id => document.getElementById(id);
const base = location.origin;
const parts = location.pathname.split('/').filter(Boolean);
const params = new URLSearchParams(location.search);
let convId = parts.length && parts[parts.length-1] !== 'client' ? parts[parts.length-1] : params.get('conversation_id');
const presel = params.get('customer_id');
const LANGS = [['english','English'],['hindi','हिंदी'],['marathi','मराठी'],['hinglish','Hinglish'],['tamil','தமிழ்'],['telugu','తెలుగు'],['kannada','ಕನ್ನಡ'],['malayalam','മലയാളം'],['bengali','বাংলা'],['gujarati','ગુજરાતી'],['punjabi','ਪੰਜਾਬੀ']];
let ws, ctx, stream, node, proc, muted=false, active=false, speaking=false, retries=0, nextT=0, rate=24000, odd=null, resamp, sendBuf=[], pendingAction=null, customers=[], micPromise=null, connected=false, langSet=false;

const secure = window.isSecureContext && !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia);
if(!secure){const w=$('warn');w.style.display='block';w.innerHTML='<b>Microphone Aavailable on this connection.}

function setOrb(state,label){$('ow').dataset.state=state;if(label!==undefined)$('status').textContent=label;}
function addMsg(role,text){
  $('main').classList.remove('empty');
  const d=document.createElement('div');
  if(role==='sys'){d.className='sys';d.textContent=text;}
  else{d.className='msg '+role;d.innerHTML=(role==='agent'?'<span class="av"></span>':'')+'<div class="bub"></div>';d.querySelector('.bub').textContent=text;}
  $('log').appendChild(d);$('log').scrollTop=1e9;
}
function setStage(){const inCall=active;$('title').textContent=inCall?'':'How can I help you today?';$('title').style.display=inCall?'none':'';$('subtitle').style.display=inCall?'none':'';}
function enableChat(on){$('txt').disabled=!on;$('send').disabled=!on;$('txt').placeholder=on?'Message… (or just speak)':'Start the call to chat';}

/* ---------------- customer picker ---------------- */
async function loadCustomers(){if(customers.length)return;try{customers=await (await fetch(base+'/api/customers')).json();}catch(e){customers=[];}}
function renderList(){
  const q=$('q').value.trim().toLowerCase();
  const rows=customers.filter(c=>!q||[c.customer_id,c.full_name,c.mobile_number,c.city,c.email].join(' ').toLowerCase().includes(q));
  $('list').innerHTML='';
  rows.forEach(c=>{const b=document.createElement('button');b.className='row2';const off=c.status==='inactive';b.disabled=off;
    b.innerHTML=`<span class="ini">${(c.full_name||'?').split(' ').map(x=>x[0]).slice(0,2).join('')}</span><span><div class="n"></div><div class="m"></div></span>${off?'<span class="tag">Inactive</span>':`<span class="tag">${c.total_orders} orders</span>`}`;
    b.querySelector('.n').textContent=c.full_name;b.querySelector('.m').textContent=`${c.customer_id} · ${c.city||''}`;
    b.onclick=()=>pick(c);$('list').appendChild(b);});
  const v=document.createElement('button');v.className='row2';v.innerHTML='<span class="ini">#</span><span><div class="n">I don\'t know my customer ID</div><div class="m">The agent will verify me by registered mobile number</div></span>';
  v.onclick=()=>pick(null);$('list').appendChild(v);
}
async function openPicker(){await loadCustomers();$('q').value='';renderList();$('dlg').classList.add('open');setTimeout(()=>$('q').focus(),50);}
function closePicker(){$('dlg').classList.remove('open');}
$('q').addEventListener('input',renderList);$('cancelpick').onclick=closePicker;
$('dlg').addEventListener('click',e=>{if(e.target===$('dlg'))closePicker();});
document.addEventListener('keydown',e=>{if(e.key==='Escape')closePicker();});

/* ---------------- call lifecycle ---------------- */
function grabMic(){micPromise=secure?navigator.mediaDevices.getUserMedia({audio:{channelCount:1,echoCancellation:true,noiseSuppression:true,autoGainControl:true}}):Promise.reject(new Error('insecure'));micPromise.catch(()=>{});}
async function initAudio(){
  if(ctx)return;
  ctx=new (window.AudioContext||window.webkitAudioContext)();await ctx.resume();            // inside the tap (iOS/Safari)
  const b=ctx.createBuffer(1,1,22050),s=ctx.createBufferSource();s.buffer=b;s.connect(ctx.destination);s.start(0);
}
async function onOrb(){
  try{await initAudio();}catch(e){addMsg('sys','Audio could not start: '+(e.message||e));return;}
  if(active){muted=!muted;setOrb(muted?'muted':'listening',muted?'Muted — tap to unmute':'Listening…');return;}
  if(convId||presel){grabMic();await beginCall(presel&&!convId?presel:null);}else{await openPicker();}
}
async function pick(c){closePicker();grabMic();await beginCall(c?c.customer_id:'',c);}
async function beginCall(customerId,cObj){
  setOrb('connecting','Connecting…');
  try{
    if(!convId){
      const r=await fetch(base+'/api/conversations',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({customer_id:customerId||null})});
      const j=await r.json();if(!r.ok){addMsg('sys',j.detail||('Could not start ('+r.status+')'));setOrb('idle','Tap the speaker to start');return;}
      convId=j.conversation_id;history.replaceState(null,'',base+'/api/voice/client/'+convId);
    }
    showCustomer(cObj);
    active=true;setStage();$('end').hidden=false;$('switch').hidden=false;
    connect();
    try{const s=await micPromise;stream=s;await startMic();}catch(e){addMsg('sys',secure?'Microphone permission was denied — you can still type your messages.':'Microphone needs HTTPS — you can still type your messages.');}
  }catch(e){addMsg('sys','Could not start the call: '+(e.message||e));setOrb('idle','Tap the speaker to start');}
}
async function showCustomer(c){
  try{
    if(!c){const cv=await (await fetch(`${base}/api/conversations/${convId}`)).json();
      if(cv.customer_id){c=(await (await fetch(`${base}/api/customers/${cv.customer_id}`)).json()).profile;}}
    if(c){$('cname').textContent=c.full_name;$('cid').textContent=c.customer_id;}else{$('cname').textContent='Unverified caller';$('cid').textContent='';}
    $('cust').classList.add('show');
  }catch(e){}
}
function connect(){
  const proto=location.protocol==='https:'?'wss':'ws';
  ws=new WebSocket(`${proto}://${location.host}/api/voice/${convId}`);ws.binaryType='arraybuffer';
  ws.onopen=()=>{retries=0;connected=true;enableChat(true);setOrb('listening','Listening…');};
  ws.onclose=()=>{connected=false;enableChat(false);if(active&&retries<4){retries++;setOrb('connecting','Reconnecting…');setTimeout(connect,800*retries);}else if(active){addMsg('sys','Connection lost.');}};
  ws.onerror=()=>{};
  ws.onmessage=ev=>{if(typeof ev.data==='string')onJson(JSON.parse(ev.data));else onAudio(ev.data);};
}
function onJson(m){
  switch(m.type){
    case 'connected':if(!m.providers.stt)addMsg('sys','Speech recognition is not configured on the server — use typed input.');if(!m.providers.tts)addMsg('sys','Voice output is not configured — replies will be text only.');break;
    case 'resumed':m.messages.forEach(x=>addMsg(x.role==='agent'?'agent':'user',x.text));break;
    case 'transcript':addMsg(m.role==='agent'?'agent':'user',m.text);
      if(m.pending_action){pendingAction=m.pending_action;$('pa-text').textContent=m.pending_action.summary;$('pa').style.display='block';}else if(m.role==='agent'){$('pa').style.display='none';}break;
    case 'status':speaking=(m.state==='speaking');
      if(!muted)setOrb(m.state==='speaking'?'speaking':m.state==='thinking'?'thinking':'listening',({speaking:'Speaking…',thinking:'Thinking…',transcribing:'Listening…',listening:'Listening…'})[m.state]||'');break;
    case 'language':langSet=!!m.selected;$('langs').style.display=langSet?'none':'flex';break;
    case 'audio_start':if(!ctx)break;rate=m.sample_rate;odd=null;speaking=true;if(nextT<ctx.currentTime)nextT=ctx.currentTime+0.05;break;
    case 'audio_end':{if(!ctx)break;const wait=Math.max(0,(nextT-ctx.currentTime)*1000)+200;setTimeout(()=>{speaking=false;if(ws&&ws.readyState===1)ws.send(JSON.stringify({type:'playback_done'}));},wait);break;}
    case 'error':addMsg('sys','⚠ '+m.message);break;
    case 'tts_unavailable':case 'stt_unavailable':addMsg('sys',m.message);break;
    case 'ended':addMsg('sys','Call ended.');endCall();break;
  }
}
function onAudio(buf){
  if(!ctx)return;
  let u8=new Uint8Array(buf);if(odd!==null){const t=new Uint8Array(u8.length+1);t[0]=odd;t.set(u8,1);u8=t;odd=null;}
  if(u8.length%2){odd=u8[u8.length-1];u8=u8.subarray(0,u8.length-1);}
  const n=u8.length/2;if(!n)return;const dv=new DataView(u8.buffer,u8.byteOffset,u8.length),f=new Float32Array(n);
  for(let i=0;i<n;i++)f[i]=dv.getInt16(i*2,true)/32768;
  const ab=ctx.createBuffer(1,n,rate);ab.copyToChannel(f,0);const s=ctx.createBufferSource();s.buffer=ab;s.connect(ctx.destination);
  const t=Math.max(nextT,ctx.currentTime+0.02);s.start(t);nextT=t+ab.duration;
}
class Resampler{constructor(i,o){this.r=i/o;this.t=0;this.c=new Float32Array(0);}
  push(x){const d=new Float32Array(this.c.length+x.length);d.set(this.c);d.set(x,this.c.length);const out=[];let t=this.t;
    while(t+this.r<=d.length){const a=Math.floor(t),b=Math.max(Math.floor(t+this.r),a+1);let s=0;for(let j=a;j<b;j++)s+=d[j];out.push(s/(b-a));t+=this.r;}
    const k=Math.floor(t);this.c=d.slice(k);this.t=t-k;return out;}}
async function startMic(){
  const src=ctx.createMediaStreamSource(stream);resamp=new Resampler(ctx.sampleRate,16000);
  const onFrame=f32=>{
    let peak=0;for(let i=0;i<f32.length;i+=8)peak=Math.max(peak,Math.abs(f32[i]));
    if(!speaking&&!muted)$('ow').style.setProperty('--lvl',Math.min(1,peak*2.2).toFixed(2));
    if(muted||speaking||!ws||ws.readyState!==1)return;
    const o=resamp.push(f32);for(const v of o)sendBuf.push(Math.max(-1,Math.min(1,v)));
    while(sendBuf.length>=512){const a=new Int16Array(512);for(let i=0;i<512;i++)a[i]=Math.round(sendBuf[i]*32767);sendBuf.splice(0,512);ws.send(a.buffer);}
  };
  try{
    const code=`class P extends AudioWorkletProcessor{process(i){const c=i[0][0];if(c)this.port.postMessage(c.slice(0));return true}}registerProcessor('pcm-cap',P)`;
    await ctx.audioWorklet.addModule(URL.createObjectURL(new Blob([code],{type:'application/javascript'})));
    node=new AudioWorkletNode(ctx,'pcm-cap');node.port.onmessage=e=>onFrame(e.data);
    const mute=ctx.createGain();mute.gain.value=0;src.connect(node);node.connect(mute);mute.connect(ctx.destination);
  }catch(e){   // older browsers: ScriptProcessor fallback
    proc=ctx.createScriptProcessor(4096,1,1);proc.onaudioprocess=e=>onFrame(new Float32Array(e.inputBuffer.getChannelData(0)));
    const mute=ctx.createGain();mute.gain.value=0;src.connect(proc);proc.connect(mute);mute.connect(ctx.destination);
  }
}
function endCall(){
  const wasActive=active;active=false;
  try{if(ws&&ws.readyState===1)ws.send(JSON.stringify({type:'stop'}));}catch(e){}
  setTimeout(()=>{try{ws&&ws.close();}catch(e){}},200);
  if(stream){stream.getTracks().forEach(t=>t.stop());stream=null;}
  if(ctx){try{ctx.close();}catch(e){}ctx=null;}
  convId=null;history.replaceState(null,'',base+'/api/voice/client'+(presel?'?customer_id='+presel:''));
  muted=false;speaking=false;sendBuf=[];$('ow').style.setProperty('--lvl',0);
  $('end').hidden=true;$('switch').hidden=true;enableChat(false);$('pa').style.display='none';$('langs').style.display='none';
  setStage();setOrb('idle',wasActive?'Call ended — tap the speaker to start a new call':'Tap the speaker to start');
}
$('orb').onclick=onOrb;
$('end').onclick=endCall;
$('switch').onclick=async()=>{endCall();$('log').innerHTML='';$('main').classList.add('empty');$('cust').classList.remove('show');try{await initAudio();}catch(e){}await openPicker();};
$('form').onsubmit=e=>{e.preventDefault();const t=$('txt').value.trim();if(!t||!ws||ws.readyState!==1)return;ws.send(JSON.stringify({type:'text',text:t}));$('txt').value='';};
$('langs').innerHTML=LANGS.map(([k,n])=>`<button type="button" data-k="${k}">${n}</button>`).join('');
$('langs').onclick=e=>{const k=e.target.dataset&&e.target.dataset.k;if(k&&ws&&ws.readyState===1)ws.send(JSON.stringify({type:'select_language',language:k}));};
async function decide(d){if(!pendingAction)return;
  const r=await fetch(`${base}/api/conversations/${convId}/confirm-action`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action_id:pendingAction.action_id,decision:d})});
  const j=await r.json().catch(()=>({}));$('pa').style.display='none';pendingAction=null;if(!r.ok)addMsg('sys','Could not complete: '+(j.detail||r.status));}
$('pa-yes').onclick=()=>decide('confirm');$('pa-no').onclick=()=>decide('reject');
window.addEventListener('beforeunload',()=>{try{ws&&ws.close();}catch(e){}});
if(presel)$('subtitle').textContent='Tap the speaker to start the call.';
if(convId){$('subtitle').textContent='Tap the speaker to resume this call.';}
})();
</script></body></html>
'''


def render_client_page() -> str:
    return PAGE
