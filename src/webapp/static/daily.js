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

  async function summarizeOne(btn){
    try{
      if (!btn) return;
      const id = btn.getAttribute('data-article-id');
      if (!id) return;
      
      // Сохраняем исходный текст кнопки ("Нет")
      const originalText = btn.textContent;
      
      // Меняем состояние кнопки: делаем неактивной и добавляем анимацию к слову "Нет"
      btn.disabled = true;
      // Не меняем текст, оставляем "Нет", но добавляем класс processing для анимации
      btn.classList.add('processing');
      
      try {
        const resp = await fetch('/articles/' + encodeURIComponent(id) + '/summarize', { method: 'POST' });
        if (!resp.ok) {
          throw new Error('HTTP ' + resp.status);
        }
        const j = await resp.json();
        
        if (j && (j.ok === true || j.summary_text)){
          // Заменяем кнопку на зелёный бейдж
          const okSpan = document.createElement('span');
          okSpan.className = 'badge success';
          okSpan.textContent = 'Есть';
          btn.replaceWith(okSpan);
        } else {
          throw new Error('Сервис вернул неожиданный ответ');
        }
      } catch(e) {
        alert('Не удалось сгенерировать резюме: ' + (e && e.message ? e.message : e));
        // Восстанавливаем кнопку: возвращаем исходный текст и убираем анимацию
        btn.disabled = false;
        btn.textContent = originalText; // "Нет"
        btn.classList.remove('processing');
      }
    } catch(e){
      alert('Не удалось сгенерировать резюме: ' + (e && e.message ? e.message : e));
      // Пытаемся восстановить кнопку в любом случае
      try {
        btn.disabled = false;
        btn.textContent = 'Нет';
        btn.classList.remove('processing');
      } catch(_) {}
    }
  }



  function refresh(){ location.reload(); }

  // Bindings
  var ingestBtn = document.getElementById('btn-ingest');
  if (ingestBtn) ingestBtn.addEventListener('click', ingestDay);
  var refreshBtn = document.getElementById('btn-refresh');
  if (refreshBtn) refreshBtn.addEventListener('click', refresh);

  // Делегирование клика по «Нет» (summarize)
  document.addEventListener('click', function(e){
    const target = e.target;
    if (!target) return;
    if (target.classList && target.classList.contains('summarize-btn')){
      e.preventDefault();
      summarizeOne(target);
    }
  });
})();
