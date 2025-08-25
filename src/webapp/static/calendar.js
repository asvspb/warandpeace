(function(){
  async function refreshCalendarSection(){
    try {
      const container = document.getElementById('calendar-root');
      if (!container) return;
      const y = parseInt(container.getAttribute('data-year') || '0', 10) || new Date().getFullYear();
      const m = parseInt(container.getAttribute('data-month') || '0', 10) || (new Date().getMonth() + 1);
      const resp = await fetch(`/calendar?year=${y}&month=${m}`, {headers: {'X-Requested-With':'fetch'}, cache: 'no-store'});
      if (!resp.ok) return;
      const html = await resp.text();
      const tmp = document.createElement('div'); tmp.innerHTML = html;
      const newCal = tmp.querySelector('#calendar-root');
      if (newCal) { container.innerHTML = newCal.innerHTML; }
    } catch(e) { /* no-op */ }
  }
  window.refreshCalendarSection = refreshCalendarSection;
})();
