(function(){
  async function refreshStatus(){
    const r = await fetch('/admin/backfill/status');
    const j = await r.json();
    document.getElementById('status').textContent = JSON.stringify(j, null, 2);
    try{
      document.getElementById('status-updated').textContent = new Date().toLocaleTimeString();
    }catch(e){}
  }
  async function collectStart(){
    const until = document.getElementById('collect-until').value.trim();
    const params = new URLSearchParams();
    if (until) params.set('until', until);
    await fetch('/admin/backfill/collect/start?' + params.toString(), { method: 'POST' });
    refreshStatus();
  }
  async function collectStop(){
    await fetch('/admin/backfill/collect/stop', { method: 'POST' });
    refreshStatus();
  }
  async function sumStart(){
    const until = document.getElementById('sum-until').value.trim();
    const model = document.getElementById('sum-model').value;
    const params = new URLSearchParams();
    if (until) params.set('until', until);
    if (model) params.set('model', model);
    await fetch('/admin/backfill/summarize/start?' + params.toString(), { method: 'POST' });
    refreshStatus();
  }
  async function sumStop(){
    await fetch('/admin/backfill/summarize/stop', { method: 'POST' });
    refreshStatus();
  }

  function ready(fn){
    if (document.readyState !== 'loading') { fn(); } else { document.addEventListener('DOMContentLoaded', fn); }
  }

  ready(function(){
    document.getElementById('btn-refresh').addEventListener('click', refreshStatus);
    document.getElementById('btn-collect-start').addEventListener('click', collectStart);
    document.getElementById('btn-collect-stop').addEventListener('click', collectStop);
    document.getElementById('btn-sum-start').addEventListener('click', sumStart);
    document.getElementById('btn-sum-stop').addEventListener('click', sumStop);
    refreshStatus();
  });
})();
