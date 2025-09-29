// Тесты для фронтенд-логики календаря в calendar.js
// Эти тесты проверяют автоматическое обновление календаря

describe('Calendar Frontend Logic', () => {
    // Мокаем fetch для тестирования
    let originalFetch;
    let originalSetInterval;

    beforeEach(() => {
        // Сохраняем оригинальные функции
        originalFetch = window.fetch;
        originalSetInterval = window.setInterval;

        // Мокаем fetch
        window.fetch = vi.fn(() =>
            Promise.resolve({
                ok: true,
                text: () => Promise.resolve('<div id="calendar-root">Mock calendar content</div>')
            })
        );

        // Мокаем setInterval, чтобы не запускать автоматические обновления во время тестов
        window.setInterval = vi.fn((fn) => {
            // Вызываем функцию один раз для тестирования, но не устанавливаем интервал
            fn();
            return null;
        });

        // Создаем тестовый DOM элемент
        document.body.innerHTML = `
            <div id="calendar-root" data-year="2023" data-month="3">
                <div class="calendar-header">Original content</div>
            </div>
        `;
    });

    afterEach(() => {
        // Восстанавливаем оригинальные функции
        window.fetch = originalFetch;
        window.setInterval = originalSetInterval;

        // Очищаем DOM
        document.body.innerHTML = '';
        // Удаляем глобальные переменные, если они были добавлены
        if (window.refreshCalendarSection) {
            delete window.refreshCalendarSection;
        }
    });

    test('should define refreshCalendarSection function', () => {
        // Выполняем скрипт напрямую, чтобы IIFE сработал
        const scriptContent = require('fs').readFileSync(require.resolve('../../../src/webapp/static/calendar.js'), 'utf8');
        eval(scriptContent);

        // Проверяем, что функция определена
        expect(window.refreshCalendarSection).toBeDefined();
        expect(typeof window.refreshCalendarSection).toBe('function');
    });

    test('should fetch calendar fragment and update DOM', async () => {
        // Выполняем скрипт напрямую, чтобы IIFE сработал
        const scriptContent = require('fs').readFileSync(require.resolve('../../../src/webapp/static/calendar.js'), 'utf8');
        eval(scriptContent);

        // Проверяем начальное состояние
        const container = document.getElementById('calendar-root');
        expect(container.innerHTML).toContain('Original content');

        // Вызываем функцию обновления
        await window.refreshCalendarSection();

        // Проверяем, что fetch был вызван с правильным URL
        expect(window.fetch).toHaveBeenCalledWith(
            '/calendar?year=2023&month=3&fragment=1',
            {
                headers: { 'X-Requested-With': 'fetch' },
                cache: 'no-store'
            }
        );

        // Проверяем, что содержимое обновилось
        expect(container.innerHTML).toBe('<div id="calendar-root">Mock calendar content</div>');
    });

    test('should use current date if no data attributes are present', async () => {
        // Создаем элемент без атрибутов данных
        document.body.innerHTML = `
            <div id="calendar-root">
                <div class="calendar-header">Original content</div>
            </div>
        `;

        // Выполняем скрипт напрямую, чтобы IIFE сработал
        const scriptContent = require('fs').readFileSync(require.resolve('../../../src/webapp/static/calendar.js'), 'utf8');
        eval(scriptContent);

        // Вызываем функцию обновления
        await window.refreshCalendarSection();

        // Получаем вызов fetch
        const fetchCall = window.fetch.mock.calls[0][0];

        // Проверяем, что URL содержит текущий год и месяц
        const today = new Date();
        const currentYear = today.getFullYear();
        const currentMonth = today.getMonth() + 1; // JS месяцы с 0, но в URL нужно с 1

        expect(fetchCall).toContain(`year=${currentYear}`);
        expect(fetchCall).toContain(`month=${currentMonth}`);
        expect(fetchCall).toContain('&fragment=1');
    });

    test('should handle fetch errors gracefully', async () => {
        // Мокаем fetch с ошибкой
        window.fetch = vi.fn(() => Promise.reject(new Error('Network error')));

        // Выполняем скрипт напрямую, чтобы IIFE сработал
        const scriptContent = require('fs').readFileSync(require.resolve('../../../src/webapp/static/calendar.js'), 'utf8');
        eval(scriptContent);

        // Проверяем, что функция не падает при ошибке fetch
        await expect(window.refreshCalendarSection()).resolves.not.toThrow();
    });

    test('should handle non-OK response gracefully', async () => {
        // Мокаем fetch с неуспешным ответом
        window.fetch = vi.fn(() =>
            Promise.resolve({
                ok: false,
                status: 500
            })
        );

        // Выполняем скрипт напрямую, чтобы IIFE сработал
        const scriptContent = require('fs').readFileSync(require.resolve('../../../src/webapp/static/calendar.js'), 'utf8');
        eval(scriptContent);

        // Проверяем, что функция не падает при неуспешном ответе
        await expect(window.refreshCalendarSection()).resolves.not.toThrow();
    });

    test('should set interval for automatic refresh every 5 minutes', () => {
        // Выполняем скрипт напрямую, чтобы IIFE сработал
        const scriptContent = require('fs').readFileSync(require.resolve('../../../src/webapp/static/calendar.js'), 'utf8');
        eval(scriptContent);

        // Проверяем, что setInterval был вызван с правильным интервалом (5 минут = 30000 мс)
        expect(window.setInterval).toHaveBeenCalledWith(
            expect.any(Function),
            300000
        );
    });

    test('should not execute if calendar container is not found', async () => {
        // Удаляем контейнер календаря
        document.body.innerHTML = '';

        // Выполняем скрипт напрямую, чтобы IIFE сработал
        const scriptContent = require('fs').readFileSync(require.resolve('../../../src/webapp/static/calendar.js'), 'utf8');
        eval(scriptContent);

        // Вызываем функцию обновления
        await window.refreshCalendarSection();

        // Проверяем, что fetch не был вызван
        expect(window.fetch).not.toHaveBeenCalled();
    });
});