(function () {
  // Маппинг для отслеживания задач суммаризации по ID задач
  const summarizationJobs = new Map();
  
  // Функция для сохранения задач в localStorage
  function saveJobsToStorage() {
    const jobsArray = Array.from(summarizationJobs.entries()).map(([jobId, jobInfo]) => ({
      jobId,
      ...jobInfo
    }));
    localStorage.setItem('summarizationJobs', JSON.stringify(jobsArray));
  }
  
  // Функция для загрузки задач из localStorage
  function loadJobsFromStorage() {
    const jobsData = localStorage.getItem('summarizationJobs');
    if (jobsData) {
      try {
        const jobsArray = JSON.parse(jobsData);
        jobsArray.forEach(job => {
          summarizationJobs.set(job.jobId, {
            articleId: job.articleId,
            status: job.status,
            updatedAt: job.updatedAt ? new Date(job.updatedAt) : new Date()
          });
        });
      } catch (e) {
        console.error('Error loading jobs from storage:', e);
      }
    }
  }
  
  // Функция для очистки завершенных задач из localStorage
  function cleanupCompletedJobsFromStorage() {
    const jobsArray = Array.from(summarizationJobs.entries()).map(([jobId, jobInfo]) => ({
      jobId,
      ...jobInfo
    }));
    
    // Сохраняем только незавершенные задачи
    const pendingJobs = jobsArray.filter(job =>
      !['finished', 'completed', 'failed', 'error'].includes(job.status)
    );
    
    localStorage.setItem('summarizationJobs', JSON.stringify(pendingJobs));
  }
  
  // Функция для проверки статуса задачи суммаризации
  async function checkJobStatus(jobId) {
    try {
      const response = await fetch(`/api/summarization/status/${jobId}`);
      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }
      return await response.json();
    } catch (error) {
      console.error('Error checking job status:', error);
      return { status: 'error', error: error.message };
    }
  }

  // Функция для обновления индикатора статуса на элементе
  function updateStatusIndicator(element, status) {
    // Удаляем старые классы статуса
    element.classList.remove('pending', 'processing', 'success', 'error');
    
    // Добавляем новый класс в зависимости от статуса
    if (status === 'queued' || status === 'pending') {
      element.classList.add('pending');
      element.title = 'В очереди на резюмирование';
    } else if (status === 'started' || status === 'processing') {
      element.classList.add('processing');
      element.title = 'Идет резюмирование';
    } else if (status === 'finished' || status === 'completed') {
      element.classList.add('success');
      element.title = 'Резюме готово';
    } else if (status === 'failed' || status === 'error') {
      element.classList.add('error');
      element.title = 'Ошибка резюмирования';
    }
  }

  // Функция для периодической проверки статуса задач
  async function pollJobStatuses() {
    // Сначала обновляем информацию о задачах из localStorage
    loadJobsFromStorage();
    
    for (const [jobId, jobInfo] of summarizationJobs.entries()) {
      const statusInfo = await checkJobStatus(jobId);
      const status = statusInfo.status;
      
      // Обновляем статус задачи
      jobInfo.status = status;
      jobInfo.updatedAt = new Date();
      
      // Находим соответствующий элемент в DOM и обновляем его
      const dayElement = document.querySelector(`[data-article-ids*="${jobInfo.articleId}"]`);
      if (dayElement) {
        const statusElement = dayElement.querySelector('.summary');
        if (statusElement) {
          updateStatusIndicator(statusElement, status);
          
          // Если задача завершена, обновляем также и текст с количеством
          if (status === 'finished' || status === 'completed') {
            // Извлекаем текущую информацию о суммаризации
            const currentText = statusElement.textContent;
            const parts = currentText.split('/');
            if (parts.length === 2) {
              // Увеличиваем количество суммаризованных статей на 1
              const summarized = parseInt(parts[0]) + 1;
              const total = parseInt(parts[1]);
              statusElement.textContent = `${summarized}/${total}`;
              
              // Обновляем общий статус дня
              if (summarized >= total && total > 0) {
                statusElement.classList.add('success');
              }
            }
          }
        }
      }
      
      // Если задача завершена (успешно или с ошибкой), удаляем её из маппинга
      if (['finished', 'completed', 'failed', 'error'].includes(status)) {
        summarizationJobs.delete(jobId);
      }
    }
    
    // Сохраняем обновленную информацию в localStorage
    saveJobsToStorage();
    // Очищаем завершенные задачи из localStorage
    cleanupCompletedJobsFromStorage();
  }

  // Функция для запуска опроса статусов задач
  function startStatusPolling() {
    // Проверяем статусы каждые 5 секунд
    setInterval(pollJobStatuses, 5000);
  }

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
      
      // После обновления календаря перезапускаем отслеживание задач
      // для обновления DOM-элементов
      updateAllStatusIndicators();
    } catch (e) { /* no-op */ }
  }

  // Функция для обновления всех индикаторов статуса при обновлении календаря
  function updateAllStatusIndicators() {
    summarizationJobs.forEach((jobInfo, jobId) => {
      const dayElement = document.querySelector(`[data-article-ids*="${jobInfo.articleId}"]`);
      if (dayElement) {
        const statusElement = dayElement.querySelector('.summary');
        if (statusElement) {
          updateStatusIndicator(statusElement, jobInfo.status);
        }
      }
    });
  }

  // Устанавливаем автоматическое обновление каждые 5 минут (300000 мс)
  setInterval(refreshCalendarSection, 300000);

  // Запускаем опрос статусов задач
  startStatusPolling();
  
  // Загружаем задачи из localStorage при инициализации
  loadJobsFromStorage();

  window.refreshCalendarSection = refreshCalendarSection;
})();
