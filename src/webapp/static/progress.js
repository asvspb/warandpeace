(function(){
  async function refreshBackfillProgress(){
    try {
      const resp = await fetch('/backfill/status-public', {cache:'no-store'});
      if (!resp.ok) return;
      const j = await resp.json();
      const bar = document.getElementById('backfill-bar');
      const fill = document.getElementById('backfill-bar-fill');
      const text = document.getElementById('backfill-bar-text');
      if (!bar || !fill || !text) return;
      var pct = j.collect_progress_pct;
      var pages = j.collect_goal_pages;
      var total = j.collect_goal_total;
      var done = j.collect_processed;
      if (typeof pct !== 'number') pct = 0;
      fill.style.width = Math.max(0, Math.min(100, pct)) + '%';
      const period = j.collect_period || '';
      const scanning = !!j.collect_scanning;
      if (scanning){
        const sp = j.collect_scan_page|0;
        const gp = j.collect_goal_pages|0;
        text.textContent = `Сканирование ${period} — страница ${sp}/${gp}`;
      } else {
        text.textContent = `Период ${period} — ${pct}% (${done||0}/${total||0})`;
      }
    } catch(e) { /* no-op */ }
  }
  window.refreshBackfillProgress = refreshBackfillProgress;
})();
