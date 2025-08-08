# 🌿 Git Workflow & Branching Strategy

**Версия:** 1.0  
**Дата:** 2025-08-08  
**Статус:** АКТИВНЫЙ

---

## 📋 Содержание
1. [Структура веток](#структура-веток)
2. [Процесс разработки](#процесс-разработки)
3. [Code Review Process](#code-review-process)
4. [Версионирование](#версионирование)
5. [CI/CD Pipeline](#cicd-pipeline)

---

## 🌳 Структура веток

### Основные ветки (Protected)
```
main (production)
  ├── develop (staging)
  │   ├── feature/task-name
  │   ├── bugfix/issue-name
  │   └── hotfix/critical-fix
  └── release/v1.x.x
```

### Типы веток

#### `main`
- **Назначение:** Production-ready код
- **Защита:** Полная (только через PR с review)
- **Деплой:** Автоматический на production
- **Доступ:** Только maintainers

#### `develop`
- **Назначение:** Интеграционная ветка для новых фич
- **Защита:** Требуется PR review
- **Деплой:** Автоматический на staging
- **Тесты:** Полный прогон перед merge

#### `feature/*`
- **Назначение:** Разработка новой функциональности
- **Создание:** От `develop`
- **Merge:** В `develop` через PR
- **Именование:** `feature/короткое-описание`
- **Пример:** `feature/add-postgresql-support`

#### `bugfix/*`
- **Назначение:** Исправление некритичных багов
- **Создание:** От `develop`
- **Merge:** В `develop` через PR
- **Пример:** `bugfix/fix-date-parsing`

#### `hotfix/*`
- **Назначение:** Критические исправления в production
- **Создание:** От `main`
- **Merge:** В `main` И `develop`
- **Пример:** `hotfix/security-patch-cve-2025`

---

## 🔄 Процесс разработки

### 1. Начало работы над задачей

```bash
# Обновить локальный репозиторий
git checkout develop
git pull origin develop

# Создать feature ветку
git checkout -b feature/task-description

# Альтернативно для багфикса
git checkout -b bugfix/issue-number-description
```

### 2. Разработка

```bash
# Регулярные коммиты с понятными сообщениями
git add .
git commit -m "feat: add user authentication module"

# Форматирование перед коммитом
black src/
isort src/
flake8 src/

# Запуск тестов
pytest tests/
```

### 3. Синхронизация с develop

```bash
# Периодически обновляться из develop
git checkout develop
git pull origin develop
git checkout feature/your-feature
git merge develop

# Или использовать rebase для чистой истории
git rebase develop
```

### 4. Создание Pull Request

```bash
# Финальная проверка
python scripts/code_quality_check.py

# Пуш в удаленный репозиторий
git push origin feature/your-feature
```

**Шаблон PR:**
```markdown
## 📋 Описание
Краткое описание изменений

## 🎯 Решаемая задача
Closes #123 (номер issue)

## ✅ Чеклист
- [ ] Код соответствует стайлгайду (PEP8)
- [ ] Добавлены/обновлены тесты
- [ ] Тесты проходят локально
- [ ] Обновлена документация
- [ ] Нет конфликтов с develop

## 📊 Тестовое покрытие
- До: X%
- После: Y%

## 📸 Скриншоты (если применимо)
```

---

## 👀 Code Review Process

### Критерии для Review

#### 🟢 Автоматические проверки (CI)
- [ ] Все тесты проходят
- [ ] Покрытие не упало
- [ ] Linting пройден
- [ ] Нет уязвимостей в зависимостях

#### 🔍 Ручная проверка
1. **Функциональность**
   - Код решает поставленную задачу
   - Нет регрессий
   - Edge cases обработаны

2. **Качество кода**
   - Читаемость и понятность
   - SOLID принципы
   - DRY (Don't Repeat Yourself)
   - Нет "code smells"

3. **Производительность**
   - Нет очевидных проблем с производительностью
   - Оптимальные алгоритмы
   - Правильное использование async/await

4. **Безопасность**
   - Нет hardcoded секретов
   - Валидация входных данных
   - SQL injection защита

### Review Comments Format

```python
# 💡 Suggestion: Предложение улучшения
# ⚠️ Warning: Потенциальная проблема
# 🔴 Critical: Критическая проблема, блокирует merge
# ❓ Question: Требуется пояснение
# 👍 Nice: Хорошее решение
```

---

## 🏷️ Версионирование

### Semantic Versioning (SemVer)
Формат: `MAJOR.MINOR.PATCH`

- **MAJOR** - Несовместимые изменения API
- **MINOR** - Новая функциональность (обратно совместимая)
- **PATCH** - Исправления багов

### Примеры:
```
1.0.0 → 1.0.1 (bugfix)
1.0.1 → 1.1.0 (new feature)
1.1.0 → 2.0.0 (breaking change)
```

### Release Process

```bash
# 1. Создать release ветку
git checkout -b release/v1.2.0 develop

# 2. Обновить версию в файлах
# - pyproject.toml
# - __version__.py
# - CHANGELOG.md

# 3. Финальное тестирование
pytest tests/ --cov=src

# 4. Merge в main
git checkout main
git merge --no-ff release/v1.2.0

# 5. Создать тег
git tag -a v1.2.0 -m "Release version 1.2.0"
git push origin v1.2.0

# 6. Merge обратно в develop
git checkout develop
git merge --no-ff release/v1.2.0
```

---

## 🚀 CI/CD Pipeline

### GitHub Actions Workflow

```yaml
name: CI/CD Pipeline

on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main, develop]

jobs:
  quality:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Code Quality
        run: |
          black --check src/
          isort --check src/
          flake8 src/

  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Run Tests
        run: |
          pytest tests/ --cov=src --cov-report=xml
      - name: Upload Coverage
        uses: codecov/codecov-action@v3

  security:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Security Scan
        run: |
          pip-audit
          bandit -r src/

  deploy:
    if: github.ref == 'refs/heads/main'
    needs: [quality, test, security]
    runs-on: ubuntu-latest
    steps:
      - name: Deploy to Production
        run: |
          # Deployment scripts
```

---

## 📊 Метрики качества

### Минимальные требования для merge

| Метрика | Требование | Инструмент |
|---------|------------|------------|
| Тестовое покрытие | ≥60% | pytest-cov |
| Цикломатическая сложность | ≤10 | radon |
| Maintainability Index | ≥20 | radon |
| Duplicate Code | <5% | - |
| Code Smells | 0 критических | flake8 |

### Автоматические отчеты

После каждого PR автоматически генерируется отчет:
- Изменение покрытия
- Новые code smells
- Performance impact
- Security scan results

---

## 🔐 Защита веток

### Настройки для `main`:
- ✅ Require pull request reviews (2 reviewers)
- ✅ Dismiss stale pull request approvals
- ✅ Require status checks to pass
- ✅ Require branches to be up to date
- ✅ Include administrators
- ✅ Restrict who can push

### Настройки для `develop`:
- ✅ Require pull request reviews (1 reviewer)
- ✅ Require status checks to pass
- ✅ Require branches to be up to date

---

## 📝 Commit Message Convention

### Формат
```
<type>(<scope>): <subject>

<body>

<footer>
```

### Типы коммитов
- `feat:` - Новая функциональность
- `fix:` - Исправление бага
- `docs:` - Изменения в документации
- `style:` - Форматирование, отступы
- `refactor:` - Рефакторинг кода
- `test:` - Добавление тестов
- `chore:` - Обновление зависимостей, конфигов
- `perf:` - Улучшение производительности

### Примеры
```bash
feat(parser): add support for multiple date formats
fix(bot): resolve memory leak in message handler
docs(readme): update installation instructions
refactor(database): extract common query logic
test(api): add integration tests for endpoints
chore(deps): update cryptography to v45.0.0
```

---

## 🆘 Разрешение конфликтов

### При конфликте merge:
```bash
# 1. Обновить develop
git checkout develop
git pull origin develop

# 2. Вернуться в feature ветку
git checkout feature/your-feature

# 3. Начать merge
git merge develop

# 4. Разрешить конфликты в редакторе
# Искать маркеры: <<<<<<< ======= >>>>>>>

# 5. После разрешения
git add .
git commit -m "merge: resolve conflicts with develop"

# 6. Проверить что все работает
pytest tests/
```

---

## 📚 Полезные команды

```bash
# Просмотр истории
git log --oneline --graph --decorate

# Отмена последнего коммита (локально)
git reset --soft HEAD~1

# Изменить последний коммит
git commit --amend

# Очистка удаленных веток
git remote prune origin

# Найти кто внес изменения
git blame src/file.py

# Интерактивный rebase
git rebase -i HEAD~3
```

---

*Документ поддерживается AI Project Manager*  
*Последнее обновление: 2025-08-08*
