'use strict';
function b64urlToBuf(s){const pad='='.repeat((4-(s.length%4))%4);const b=(s+pad).replace(/-/g,'+').replace(/_/g,'/');const raw=atob(b);const arr=new Uint8Array(raw.length);for(let i=0;i<raw.length;i++)arr[i]=raw.charCodeAt(i);return arr.buffer}
function bufToB64url(buf){const bytes=new Uint8Array(buf);let bin='';for(let i=0;i<bytes.byteLength;i++)bin+=String.fromCharCode(bytes[i]);return btoa(bin).replace(/\+/g,'-').replace(/\//g,'_').replace(/=+$/,'')}
async function login(){
  const st = document.getElementById('login-status');
  st.textContent = 'Готовим запрос…';
  const res = await fetch('/webauthn/login/options', {method:'POST', credentials:'include'});
  const opts = await res.json();
  if(opts.detail){ st.textContent = opts.detail; return }
  opts.publicKey.challenge = b64urlToBuf(opts.publicKey.challenge);
  if(opts.publicKey.allowCredentials){
    opts.publicKey.allowCredentials = opts.publicKey.allowCredentials.map(c=>({ ...c, id: b64urlToBuf(c.id) }));
  }
  const assertion = await navigator.credentials.get(opts);
  const payload = {
    id: assertion.id,
    rawId: bufToB64url(assertion.rawId),
    type: assertion.type,
    response: {
      authenticatorData: bufToB64url(assertion.response.authenticatorData),
      clientDataJSON: bufToB64url(assertion.response.clientDataJSON),
      signature: bufToB64url(assertion.response.signature),
      userHandle: assertion.response.userHandle ? bufToB64url(assertion.response.userHandle) : null
    }
  };
  const v = await fetch('/webauthn/login/verify', {method:'POST', headers:{'Content-Type':'application/json'}, credentials:'include', body: JSON.stringify(payload)});
  const vres = await v.json().catch(()=>({}));
  if(v.ok && vres.status==='ok'){ window.location.href='/' } else { st.textContent = (vres && vres.detail) || 'Ошибка входа' }
}
window.addEventListener('DOMContentLoaded', ()=>{
  const btn = document.getElementById('btn-login');
  if(btn){
    btn.addEventListener('click', ()=>{
      if(!('credentials' in navigator)){ alert('Браузер не поддерживает WebAuthn'); return }
      login().catch(e=>{ document.getElementById('login-status').textContent = 'Ошибка: '+e })
    });
  }
});
