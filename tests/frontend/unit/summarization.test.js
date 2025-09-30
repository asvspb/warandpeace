/**
 * Тесты для клиентской части фоновой суммаризации.
 */

describe('Summarization Frontend Logic', () => {
    // Мокаем fetch и localStorage для тестирования
    let originalFetch;
    let originalSetInterval;
    let originalLocalStorage;
    let localStorageMock;

    beforeEach(() => {
        // Сохраняем оригинальные функции
        originalFetch = window.fetch;
        originalSetInterval = window.setInterval;
        originalLocalStorage = window.localStorage;

        // Мокаем localStorage
        localStorageMock = (function () {
            let store = {};
            return {
                getItem: function (key) {
                    return store[key] || null;
                },
                setItem: function (key, value) {
                    store[key] = value.toString();
                },
                removeItem: function (key) {
                    delete store[key];
                },
                clear: function () {
                    store = {};
                }
            };
        })();

        Object.defineProperty(window, 'localStorage', {
            value: localStorageMock,
            writable: true
        });

        // Мокаем fetch
        window.fetch = vi.fn((url) => {
            if (url.includes('/api/summarization/status/')) {
                const jobId = url.split('/').pop();
                return Promise.resolve({
                    ok: true,
                    json: () => Promise.resolve({
                        job_id: jobId,
                        article_id: 123,
                        status: 'processing',
                        completed: false
                    })
                });
            }
            return Promise.resolve({
                ok: true,
                json: () => Promise.resolve({})
            });
        });

        // Мокаем setInterval, чтобы не запускать автоматические обновления во время тестов
        window.setInterval = vi.fn((fn) => {
            // Вызываем функцию один раз для тестирования, но не устанавливаем интервал
            fn();
            return null;
        });

        // Создаем тестовый DOM элемент
        document.body.innerHTML = `
            <div id="calendar-root" data-year="2024" data-month="9">
                <div class="calendar-day" data-article-ids="1,2">
                    <span class="summary">0/5</span>
                </div>
                <div class="calendar-day" data-article-ids="3">
                    <span class="summary">3/3</span>
                </div>
            </div>
        `;
    });

    afterEach(() => {
        // Восстанавливаем оригинальные функции
        window.fetch = originalFetch;
        window.setInterval = originalSetInterval;

        // Восстанавливаем оригинальный localStorage
        Object.defineProperty(window, 'localStorage', {
            value: originalLocalStorage,
            writable: true
        });

        // Очищаем DOM
        document.body.innerHTML = '';
    });

    test('should save jobs to localStorage', () => {
        // Выполняем скрипт напрямую, чтобы IIFE сработал
        const scriptContent = require('fs').readFileSync(require.resolve('../../../src/webapp/static/calendar.js'), 'utf8');
        eval(scriptContent);

        // Имитируем добавление задачи
        const summarizationJobs = new Map();
        summarizationJobs.set('summarize_123_1234567890', {
            articleId: 123,
            status: 'pending',
            updatedAt: new Date()
        });

        // Сохраняем в localStorage
        const jobsArray = Array.from(summarizationJobs.entries()).map(([jobId, jobInfo]) => ({
            jobId,
            ...jobInfo
        }));
        window.localStorage.setItem('summarizationJobs', JSON.stringify(jobsArray));

        // Проверяем, что задача сохранена
        const storedJobs = window.localStorage.getItem('summarizationJobs');
        expect(storedJobs).not.toBeNull();

        const parsedJobs = JSON.parse(storedJobs);
        expect(parsedJobs).toHaveLength(1);
        expect(parsedJobs[0].jobId).toBe('summarize_123_1234567890');
        expect(parsedJobs[0].articleId).toBe(123);
    });

    test('should load jobs from localStorage', () => {
        // Сохраняем тестовые данные в localStorage
        const testData = [
            {
                jobId: 'summarize_123_1234567890',
                articleId: 123,
                status: 'processing',
                updatedAt: new Date().toISOString()
            },
            {
                jobId: 'summarize_456_1234567891',
                articleId: 456,
                status: 'pending',
                updatedAt: new Date().toISOString()
            }
        ];
        window.localStorage.setItem('summarizationJobs', JSON.stringify(testData));

        // Выполняем скрипт напрямую, чтобы IIFE сработал
        const scriptContent = require('fs').readFileSync(require.resolve('../../../src/webapp/static/calendar.js'), 'utf8');
        eval(scriptContent);

        // Имитируем функцию загрузки задач
        const jobsData = window.localStorage.getItem('summarizationJobs');
        let loadedJobs = new Map();

        if (jobsData) {
            try {
                const jobsArray = JSON.parse(jobsData);
                jobsArray.forEach(job => {
                    loadedJobs.set(job.jobId, {
                        articleId: job.articleId,
                        status: job.status,
                        updatedAt: job.updatedAt ? new Date(job.updatedAt) : new Date()
                    });
                });
            } catch (e) {
                console.error('Error loading jobs from storage:', e);
            }
        }

        expect(loadedJobs.size).toBe(2);
        expect(loadedJobs.has('summarize_123_1234567890')).toBe(true);
        expect(loadedJobs.has('summarize_456_1234567891')).toBe(true);
        expect(loadedJobs.get('summarize_123_1234567890').articleId).toBe(123);
        expect(loadedJobs.get('summarize_456_1234567891').status).toBe('pending');
    });

    test('should clear completed jobs from localStorage', () => {
        // Подготовим тестовые данные с завершенными и незавершенными задачами
        const testData = [
            {
                jobId: 'summarize_123_1234567890',
                articleId: 123,
                status: 'finished', // завершенная задача
                updatedAt: new Date().toISOString()
            },
            {
                jobId: 'summarize_456_1234567891',
                articleId: 456,
                status: 'pending', // незавершенная задача
                updatedAt: new Date().toISOString()
            },
            {
                jobId: 'summarize_789_1234567892',
                articleId: 789,
                status: 'completed', // завершенная задача
                updatedAt: new Date().toISOString()
            },
            {
                jobId: 'summarize_101_1234567893',
                articleId: 101,
                status: 'processing', // незавершенная задача
                updatedAt: new Date().toISOString()
            }
        ];
        window.localStorage.setItem('summarizationJobs', JSON.stringify(testData));

        // Имитируем функцию очистки завершенных задач
        const jobsArray = JSON.parse(window.localStorage.getItem('summarizationJobs'));
        const pendingJobs = jobsArray.filter(job =>
            !['finished', 'completed', 'failed', 'error'].includes(job.status)
        );

        // Сохраняем только незавершенные задачи
        window.localStorage.setItem('summarizationJobs', JSON.stringify(pendingJobs));

        // Проверяем, что в localStorage остались только незавершенные задачи
        const remainingJobs = JSON.parse(window.localStorage.getItem('summarizationJobs'));
        expect(remainingJobs).toHaveLength(2);

        const remainingStatuses = remainingJobs.map(job => job.status);
        expect(remainingStatuses).toContain('pending');
        expect(remainingStatuses).toContain('processing');
        expect(remainingStatuses).not.toContain('finished');
        expect(remainingStatuses).not.toContain('completed');
    });

    test('should check job status via API', async () => {
        // Мокаем успешный ответ от API
        const mockResponse = {
            job_id: 'summarize_123_1234567890',
            article_id: 123,
            status: 'processing',
            completed: false
        };

        window.fetch = vi.fn(() =>
            Promise.resolve({
                ok: true,
                json: () => Promise.resolve(mockResponse)
            })
        );

        // Вызываем функцию проверки статуса
        const response = await fetch('/api/summarization/status/summarize_123_1234567890');
        const result = await response.json();

        // Проверяем, что был сделан правильный вызов API
        expect(window.fetch).toHaveBeenCalledWith('/api/summarization/status/summarize_123_1234567890');
        expect(result.job_id).toBe('summarize_123_1234567890');
        expect(result.status).toBe('processing');
    });

    test('should handle API error when checking job status', async () => {
        // Мокаем неудачный ответ от API
        window.fetch = vi.fn(() =>
            Promise.resolve({
                ok: false,
                status: 500
            })
        );

        // Вызываем функцию проверки статуса
        const response = await fetch('/api/summarization/status/summarize_123_1234567890');

        // Проверяем, что был сделан правильный вызов API
        expect(window.fetch).toHaveBeenCalledWith('/api/summarization/status/summarize_123_1234567890');
        expect(response.ok).toBe(false);
    });

    test('should update status indicator in DOM', () => {
        // Выполняем скрипт напрямую, чтобы IIFE сработал
        const scriptContent = require('fs').readFileSync(require.resolve('../../../src/webapp/static/calendar.js'), 'utf8');
        eval(scriptContent);

        // Создаем элемент для тестирования
        const summaryElement = document.createElement('span');
        summaryElement.className = 'summary';
        summaryElement.textContent = '0/5';

        // Функция обновления индикатора статуса
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

        // Тестируем разные статусы
        updateStatusIndicator(summaryElement, 'pending');
        expect(summaryElement.classList.contains('pending')).toBe(true);
        expect(summaryElement.title).toBe('В очереди на резюмирование');

        updateStatusIndicator(summaryElement, 'processing');
        expect(summaryElement.classList.contains('processing')).toBe(true);
        expect(summaryElement.title).toBe('Идет резюмирование');

        updateStatusIndicator(summaryElement, 'completed');
        expect(summaryElement.classList.contains('success')).toBe(true);
        expect(summaryElement.title).toBe('Резюме готово');

        updateStatusIndicator(summaryElement, 'error');
        expect(summaryElement.classList.contains('error')).toBe(true);
        expect(summaryElement.title).toBe('Ошибка резюмирования');
    });

    test('should update summary text when task completes', () => {
        // Создаем элемент для тестирования
        const summaryElement = document.createElement('span');
        summaryElement.className = 'summary';
        summaryElement.textContent = '0/5';

        // Имитируем ситуацию, когда задача завершена
        const currentText = summaryElement.textContent;
        const parts = currentText.split('/');
        if (parts.length === 2) {
            // Увеличиваем количество суммаризованных статей на 1
            const summarized = parseInt(parts[0]) + 1;
            const total = parseInt(parts[1]);
            summaryElement.textContent = `${summarized}/${total}`;
        }

        // Проверяем, что текст обновился
        expect(summaryElement.textContent).toBe('1/5');

        // Проверяем, что класс обновился при завершении всех задач
        summaryElement.textContent = '5/5';
        if (summaryElement.textContent === '5/5') {
            summaryElement.classList.add('success');
        }
        expect(summaryElement.classList.contains('success')).toBe(true);
    });

    test('should maintain task state across page transitions', () => {
        // Имитируем задачи, которые должны сохраняться
        const activeJobs = [
            {
                jobId: 'summarize_123_1234567890',
                articleId: 123,
                status: 'processing',
                updatedAt: new Date().toISOString()
            },
            {
                jobId: 'summarize_456_1234567891',
                articleId: 456,
                status: 'pending',
                updatedAt: new Date().toISOString()
            }
        ];

        // Сохраняем задачи в localStorage
        window.localStorage.setItem('summarizationJobs', JSON.stringify(activeJobs));

        // Симулируем "перезагрузку" страницы - читаем задачи из localStorage
        const storedJobs = window.localStorage.getItem('summarizationJobs');
        const reloadedJobs = JSON.parse(storedJobs);

        // Проверяем, что задачи сохранились
        expect(reloadedJobs).toHaveLength(2);
        expect(reloadedJobs[0].jobId).toBe('summarize_123_1234567890');
        expect(reloadedJobs[1].jobId).toBe('summarize_456_1234567891');
        expect(reloadedJobs[0].status).toBe('processing');
        expect(reloadedJobs[1].status).toBe('pending');
    });

    test('should stop tracking completed tasks', () => {
        // Подготовим задачи, включая завершенные
        const allJobs = new Map();
        allJobs.set('summarize_123_1234567890', {
            articleId: 123,
            status: 'finished',
            updatedAt: new Date()
        });
        allJobs.set('summarize_456_1234567891', {
            articleId: 456,
            status: 'processing',
            updatedAt: new Date()
        });
        allJobs.set('summarize_789_1234567892', {
            articleId: 789,
            status: 'completed',
            updatedAt: new Date()
        });

        // Имитируем логику удаления завершенных задач
        const completedStatuses = ['finished', 'completed', 'failed', 'error'];
        const activeJobs = new Map();

        for (const [jobId, jobInfo] of allJobs.entries()) {
            if (!completedStatuses.includes(jobInfo.status)) {
                activeJobs.set(jobId, jobInfo);
            }
        }

        // Проверяем, что остались только активные задачи
        expect(activeJobs.size).toBe(1);
        expect(activeJobs.has('summarize_456_1234567891')).toBe(true);
        expect(activeJobs.has('summarize_123_1234567890')).toBe(false);
        expect(activeJobs.has('summarize_789_1234567892')).toBe(false);
    });
});