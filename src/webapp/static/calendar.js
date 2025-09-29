(function () {
  async function refreshCalendarSection() {
    try {
      const container = document.getElementById('calendar-root');
      if (!container) return;
      const y = parseInt(container.getAttribute('data-year') || '0', 10) || new Date().getFullYear();
      const m = parseInt(container.getAttribute('data-month') || '0', 10) || (new Date().getMonth() + 1);
      // Добавляем параметр для указания, что это AJAX-запрос для получения только фрагмента
      const resp = await fetch(`/calendar?year=${y}&month=${m}&fragment=1`, { headers: { 'X-Requested-With': 'fetch' }, cache: 'no-store' });
      if (!resp.ok) return;
      const html = await resp.text();
      // При получении фрагмента обновляем только содержимое календаря
      container.innerHTML = html;
    } catch (e) { /* no-op */ }
  }

  // Устанавливаем автоматическое обновление каждые 5 минут (300000 мс)
  setInterval(refreshCalendarSection, 300000);

  window.refreshCalendarSection = refreshCalendarSection;
})();
