'use strict';
function b64urlToBuf(s){const pad='='.repeat((4-(s.length%4))%4);const b=(s+pad).replace(/-/g,'+').replace(/_/g,'/');const raw=atob(b);const arr=new Uint8Array(raw.length);for(let i=0;i<raw.length;i++)arr[i]=raw.charCodeAt(i);return arr.buffer}
function bufToB64url(buf){const bytes=new Uint8Array(buf);let bin='';for(let i=0;i<bytes.byteLength;i++)bin+=String.fromCharCode(bytes[i]);return btoa(bin).replace(/\+/g,'-').replace(/\//g,'_').replace(/=+$/,'')}
async function registerKey(){
  const st = document.getElementById('reg-status');
  st.textContent = 'Готовим параметры…';
  const res = await fetch('/webauthn/register/options', {method:'POST', credentials:'include'});
  const opts = await res.json();
  if(opts.detail){ st.textContent = opts.detail; return }
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
  const v = await fetch('/webauthn/register/verify', {method:'POST', headers:{'Content-Type':'application/json'}, credentials:'include', body: JSON.stringify(payload)});
  const vres = await v.json().catch(()=>({}));
  if(v.ok && vres.status==='ok'){ st.textContent='Ключ привязан'; } else { st.textContent = (vres && vres.detail) || 'Ошибка регистрации' }
}
window.addEventListener('DOMContentLoaded', ()=>{
  const btn = document.getElementById('btn-register');
  if(btn){
    btn.addEventListener('click', ()=>{
      if(!('credentials' in navigator)){ alert('Браузер не поддерживает WebAuthn'); return }
      registerKey().catch(e=>{ document.getElementById('reg-status').textContent = 'Ошибка: '+e })
    });
  }
});
