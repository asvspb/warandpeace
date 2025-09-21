(function(){
  function onReady(fn){
    if (document.readyState !== 'loading') fn();
    else document.addEventListener('DOMContentLoaded', fn);
  }
  onReady(()=>{
    const btn = document.getElementById('btn-dashboard-refresh');
    if (btn){
      btn.addEventListener('click', async ()=>{
        try {
          if (window.refreshBackfillProgress) await window.refreshBackfillProgress();
          if (window.refreshCalendarSection) await window.refreshCalendarSection();
        } catch(e) { /* no-op */ }
      });
    }
  });
})();
