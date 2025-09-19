'use strict';

function b64urlToBuf(s){
  const pad='='.repeat((4-(s.length%4))%4);
  const b=(s+pad).replace(/-/g,'+').replace(/_/g,'/');
  const raw=atob(b);
  const arr=new Uint8Array(raw.length);
  for(let i=0;i<raw.length;i++) arr[i]=raw.charCodeAt(i);
  return arr.buffer;
}

function bufToB64url(buf){
  const bytes=new Uint8Array(buf);
  let bin='';
  for(let i=0;i<bytes.byteLength;i++) bin+=String.fromCharCode(bytes[i]);
  return btoa(bin).replace(/\+/g,'-').replace(/\//g,'_').replace(/=+$/,'');
}

async function parseJsonSafe(res){
  const text = await res.text();
  try { return {json: JSON.parse(text), text}; } catch { return {json: null, text}; }
}

async function registerKey(){
  const st = document.getElementById('reg-status');
  st.textContent = 'Готовим параметры…';
  try {
    const res = await fetch('/webauthn/register/options', {method:'POST', credentials:'include'});
    const {json: opts, text: raw} = await parseJsonSafe(res);
    if(!res.ok){ st.textContent = `Ошибка ${res.status}: ${(opts && opts.detail) || raw || 'Неизвестная ошибка'}`; return; }
    if(!opts || !opts.publicKey){ st.textContent = 'Некорректный ответ сервера'; return; }

    opts.publicKey.user.id = b64urlToBuf(opts.publicKey.user.id);
    opts.publicKey.challenge = b64urlToBuf(opts.publicKey.challenge);
    if(opts.publicKey.excludeCredentials){
      opts.publicKey.excludeCredentials = opts.publicKey.excludeCredentials.map(c=>({ ...c, id: b64urlToBuf(c.id) }));
    }

    const cred = await navigator.credentials.create(opts);
    const payload = {
      id: cred.id,
      rawId: bufToB64url(cred.rawId),
      type: cred.type,
      response: {
        attestationObject: bufToB64url(cred.response.attestationObject),
        clientDataJSON: bufToB64url(cred.response.clientDataJSON)
      }
    };

    const v = await fetch('/webauthn/register/verify', {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      credentials:'include',
      body: JSON.stringify(payload)
    });
    const {json: vres, text: vraw} = await parseJsonSafe(v);
    if(v.ok && vres && vres.status==='ok'){
      st.textContent='Ключ привязан';
    } else {
      st.textContent = (vres && vres.detail) || vraw || 'Ошибка регистрации';
    }
  } catch(e){
    st.textContent = `Ошибка: ${e && e.message ? e.message : e}`;
  }
}

window.addEventListener('DOMContentLoaded', ()=>{
  const btn = document.getElementById('btn-register');
  if(btn){
    btn.addEventListener('click', ()=>{
      if(!('credentials' in navigator)){
        alert('Браузер не поддерживает WebAuthn');
        return;
      }
      registerKey().catch(e=>{ document.getElementById('reg-status').textContent = 'Ошибка: '+e });
    });
  }
});
