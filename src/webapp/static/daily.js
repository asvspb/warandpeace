(function(){
  async function ingestDay(){
    try {
      var root = document.getElementById('daily-root');
      if (!root) return;
      var day = root.getAttribute('data-day');
      if (!day) return;
      const resp = await fetch('/day/' + encodeURIComponent(day) + '/ingest', { method: 'POST' });
      if (!resp.ok) { alert('Не удалось запустить сбор.'); return; }
      const j = await resp.json();
      if (j && j.started) {
        alert('Сбор запущен. Обновите страницу через минуту.');
      } else {
        alert('Сервис вернул неожиданный ответ.');
      }
    } catch(e) {
      alert('Ошибка сети при запуске сбора.');
    }
  }
  function refresh(){ location.reload(); }
  var ingestBtn = document.getElementById('btn-ingest');
  if (ingestBtn) ingestBtn.addEventListener('click', ingestDay);
  var refreshBtn = document.getElementById('btn-refresh');
  if (refreshBtn) refreshBtn.addEventListener('click', refresh);
})();
