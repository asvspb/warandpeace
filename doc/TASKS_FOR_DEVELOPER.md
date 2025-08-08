# 📋 ЗАДАЧИ ДЛЯ РАЗРАБОТЧИКА - War and Peace Project

**Роль:** Вы - ИИ-разработчик, ответственный за реализацию технических задач согласно данной спецификации.  
**Дата создания:** 2025-08-08  
**Приоритет:** КРИТИЧНЫЙ → ВЫСОКИЙ → СРЕДНИЙ → НИЗКИЙ

---

## 🔴 КРИТИЧНЫЕ ЗАДАЧИ (Выполнить немедленно)

### 1. Обновление критических зависимостей с уязвимостями
**Срок:** В течение 24 часов  
**Контекст:** Обнаружены устаревшие пакеты с известными CVE уязвимостями

**Технические требования:**
1. Обновить в `requirements.txt`:
   ```
   cryptography>=45.0.0  # Текущая: 3.4.8
   Pillow>=11.0.0       # Текущая: 9.0.1
   PyYAML>=6.0.1        # Текущая: 5.4.1
   Django>=5.0.0        # Текущая: 3.2.12 (если используется)
   SQLAlchemy>=2.0.30   # Текущая: 2.0.36
   ```

2. **ВАЖНО:** После обновления запустить полный тестовый прогон:
   ```bash
   pytest tests/ -v
   python scripts/manage.py test-integration
   ```

3. Проверить совместимость с текущим кодом, особенно:
   - Изменения API в cryptography
   - Изменения в обработке изображений Pillow
   - Изменения в YAML парсинге

---

### 2. Увеличение тестового покрытия критических модулей
**Срок:** В течение 48 часов  
**Текущее покрытие:** 25% (КРИТИЧНО НИЗКОЕ)  
**Целевое покрытие:** минимум 60%

**Модули требующие покрытия (приоритет):**

#### A. `src/bot.py` (0% → 80%)
Создать файл `tests/test_bot.py` с тестами:
```python
# Структура тестов для bot.py
class TestBotFunctions:
    def test_check_and_post_news():
        """Тест основной функции постинга новостей"""
        # Мок telegram API
        # Мок database функций
        # Проверка корректной отправки сообщений
        
    def test_start_command():
        """Тест команды /start"""
        
    def test_status_command():
        """Тест команды /status с различными состояниями БД"""
        
    def test_daily_digest_creation():
        """Тест создания ежедневного дайджеста"""
        # Мок данных из БД
        # Проверка форматирования
        # Проверка отправки
```

#### B. `src/async_parser.py` (0% → 70%)
Создать файл `tests/test_async_parser.py`:
```python
# Структура тестов
class TestAsyncParser:
    @pytest.mark.asyncio
    async def test_fetch_news_list():
        """Тест получения списка новостей"""
        # Мок HTTP запросов
        # Проверка парсинга HTML
        
    @pytest.mark.asyncio
    async def test_fetch_article():
        """Тест получения полной статьи"""
        
    @pytest.mark.asyncio
    async def test_date_parsing():
        """Тест парсинга различных форматов дат"""
```

#### C. `src/database.py` (50% → 85%)
Дополнить существующие тесты:
```python
# Добавить в tests/test_database.py
def test_add_digest():
    """Тест добавления дайджеста"""
    
def test_get_digests_for_period():
    """Тест получения дайджестов за период"""
    
def test_update_article_backfill_status():
    """Тест обновления статуса backfill"""
```

---

## 🟠 ВЫСОКИЙ ПРИОРИТЕТ

### 3. Рефакторинг функции check_and_post_news
**Проблема:** Цикломатическая сложность = 12 (максимум должен быть 10)  
**Файл:** `src/bot.py`, строка 31

**План рефакторинга:**
```python
# Разбить на отдельные функции:

async def fetch_new_articles(hours: int = 24) -> List[Article]:
    """Получить новые статьи за указанный период"""
    pass

async def filter_unpublished_articles(articles: List[Article]) -> List[Article]:
    """Отфильтровать уже опубликованные статьи"""
    pass

async def summarize_articles(articles: List[Article]) -> List[ArticleWithSummary]:
    """Создать резюме для списка статей"""
    pass

async def publish_to_telegram(article: ArticleWithSummary, context) -> bool:
    """Опубликовать одну статью в Telegram"""
    pass

async def check_and_post_news(context: ContextTypes.DEFAULT_TYPE):
    """Обновленная главная функция - оркестратор"""
    articles = await fetch_new_articles()
    unpublished = await filter_unpublished_articles(articles)
    
    for article in unpublished[:3]:  # Лимит постов
        summary = await summarize_articles([article])
        if summary:
            await publish_to_telegram(summary[0], context)
            await asyncio.sleep(10)  # Пауза между публикациями
```

---

### 4. Устранение дублирования кода между парсерами
**Проблема:** Идентичная логика в `src/parser.py` и `src/async_parser.py`  
**Решение:** Создать общий модуль

**Создать файл** `src/common/parser_utils.py`:
```python
"""Общие утилиты для парсинга"""
from datetime import datetime
from typing import Optional, Dict, Any
from bs4 import BeautifulSoup

def parse_custom_date(date_str: str) -> Optional[datetime]:
    """Универсальный парсер дат для различных форматов"""
    # Общая логика парсинга дат
    pass

def extract_article_metadata(soup: BeautifulSoup) -> Dict[str, Any]:
    """Извлечь метаданные статьи из HTML"""
    # Общая логика извлечения данных
    pass

def clean_html_content(html: str) -> str:
    """Очистить HTML от лишних тегов"""
    pass

# Декоратор для retry логики
def with_retry(attempts=3, delay=1):
    """Универсальный декоратор для повторных попыток"""
    pass
```

Затем обновить оба парсера для использования общих функций.

---

## 🟡 СРЕДНИЙ ПРИОРИТЕТ

### 5. Настройка pre-commit hooks
**Цель:** Автоматическая проверка качества кода перед коммитом

**Файл** `.pre-commit-config.yaml` уже создан, нужно:
1. Установить pre-commit:
   ```bash
   pip install pre-commit
   pre-commit install
   ```

2. Проверить конфигурацию:
   ```bash
   pre-commit run --all-files
   ```

3. Добавить в README.md инструкцию для разработчиков

---

### 6. Завершение миграции конфигурации
**Оставшиеся задачи из PLANNING.md:**

1. **Обновить `.env.example`:**
   ```env
   # Telegram Configuration
   TELEGRAM_BOT_TOKEN=your_bot_token_here
   TELEGRAM_CHANNEL_ID=@your_channel_id
   TELEGRAM_ADMIN_IDS=123456789,987654321  # CSV список админов
   
   # Google API Configuration
   GOOGLE_API_KEYS=key1,key2,key3  # CSV список ключей
   GEMINI_MODEL_NAME=models/gemini-2.0-flash-thinking-exp-01-21
   
   # Database
   DATABASE_URL=sqlite:///data/news.db  # или postgresql://...
   ```

2. **Обновить `DEPLOYMENT.md`** с новыми переменными окружения

3. **Найти и обновить код использующий `TELEGRAM_ADMIN_IDS`**

---

## 🟢 НИЗКИЙ ПРИОРИТЕТ

### 7. Улучшение документации
1. Добавить docstrings во все функции (формат Google Style)
2. Создать API документацию с помощью Sphinx
3. Обновить README.md с актуальными примерами

### 8. Оптимизация производительности
1. Добавить индексы в БД для часто используемых запросов
2. Реализовать пулинг соединений для async операций
3. Добавить кэширование для повторяющихся запросов

---

## 📊 Метрики успеха для каждой задачи

| Задача | Критерий успеха | Как проверить |
|--------|-----------------|---------------|
| Обновление зависимостей | Все тесты проходят, нет уязвимостей | `pytest && pip-audit` |
| Тестовое покрытие | ≥60% общее, ≥80% для критичных модулей | `pytest --cov=src --cov-report=term` |
| Рефакторинг bot.py | Сложность ≤10 для всех функций | `radon cc src/bot.py -s` |
| Устранение дублирования | Общий код вынесен в utils | Code review |
| Pre-commit hooks | Автоматическая проверка работает | `git commit` запускает проверки |

---

## 🚀 Порядок выполнения

1. **День 1:** Задачи 1-2 (критичные)
2. **День 2-3:** Задачи 3-4 (высокий приоритет)
3. **День 4-5:** Задачи 5-6 (средний приоритет)
4. **По возможности:** Задачи 7-8 (низкий приоритет)

---

## ⚠️ ВАЖНЫЕ ЗАМЕЧАНИЯ

1. **НЕ ИЗМЕНЯЙТЕ** функциональность без обсуждения с PM
2. **ВСЕГДА** запускайте тесты после изменений
3. **ДОКУМЕНТИРУЙТЕ** все изменения в коммитах
4. **ИСПОЛЬЗУЙТЕ** feature branches для каждой задачи:
   ```bash
   git checkout -b feature/task-1-update-dependencies
   # После завершения
   git add .
   git commit -m "fix(security): update vulnerable dependencies"
   git push origin feature/task-1-update-dependencies
   ```

5. **Формат коммитов:**
   - `fix:` - исправление багов
   - `feat:` - новая функциональность
   - `refactor:` - рефакторинг кода
   - `test:` - добавление тестов
   - `docs:` - обновление документации
   - `chore:` - обновление зависимостей, конфигов

---

*Документ создан AI Project Manager для координации разработки*  
*При возникновении вопросов обращайтесь к PM для уточнения требований*
