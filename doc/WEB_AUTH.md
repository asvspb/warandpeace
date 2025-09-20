# Аутентификация администратора по криптографическому ключу (WebAuthn/FIDO2)

Данное руководство описывает, как реализовать вход администратора в веб‑приложение по криптографическому ключу (WebAuthn/FIDO2) вместо пароля. Приведены архитектура, модели данных, API‑эндпоинты, фронтенд‑код, чеклисты безопасности, а также альтернативный вариант на mTLS. Примеры даны для Django и FastAPI.

Время чтения: ~25–35 минут. Уровень: Middle.

---

## 1. Обзор

- Что такое WebAuthn: стандарт W3C, позволяющий браузеру безопасно работать с аутентификаторами (встроенные в ОС: Touch ID/Windows Hello/Android; внешние: YubiKey и т. п.).
- Принцип: у пользователя есть пара ключей. Публичный ключ хранится на сервере, приватный — на устройстве. При входе сервер выдаёт challenge, клиент подписывает его приватным ключом, сервер проверяет подпись публичным ключом.
- Преимущества: защита от фишинга и перебора паролей, отсутствие паролей у пользователя, удобство (биометрия/пин).

---

## 2. Архитектура и поток

- Регистрация ключа (enrollment):
  1) Пользователь (администратор) инициирует привязку ключа (уже будучи известным системе — например, созданным супер‑админом).
  2) Бэкенд генерирует `challenge` и PublicKeyCredentialCreationOptions, сохраняет `challenge` в сессии/БД.
  3) Фронтенд вызывает `navigator.credentials.create(options)`.
  4) Клиент возвращает аттестацию (attestation). Бэкенд её верифицирует и сохраняет credential: `credential_id`, `public_key`, `sign_count`, `user_id`, метаданные.

- Вход (assertion):
  1) Админ вводит свой логин/идентификатор (или выбирается автоматически, если у вас single‑admin панель).
  2) Бэкенд генерирует `challenge` и PublicKeyCredentialRequestOptions, включает `allowCredentials` с ID ключей.
  3) Фронтенд вызывает `navigator.credentials.get(options)`.
  4) Бэкенд верифицирует подпись и `sign_count`, устанавливает сессию/выдаёт токен с ролью администратора.

- Авторизация: защищайте админ‑маршруты по сессии/токену и роли (`is_admin`/`is_staff`).

---

## 3. Модель данных

Минимально необходимая таблица для ключей (псевдо‑схема):

- `webauthn_credential`:
  - `id` (PK)
  - `user_id` (FK на `user`)
  - `credential_id` (BLOB/VARBINARY; храните как bytes/base64url)
  - `public_key` (BLOB; COSE/PK)
  - `sign_count` (INT; обновляется при каждом входе)
  - `transports` (TEXT; usb/nfc/ble/internal)
  - `aaguid` (UUID; опционально)
  - `created_at`, `last_used_at`

В `user` добавьте флаг роли: `is_admin`/`is_staff`/`is_superuser`.

---

## 4. Библиотеки

- Серверная верификация (Python):
  - `python-fido2` (Yubico) или `webauthn` (Duo Labs). Обе подходят. Для Django есть адаптеры/примеры. Для FastAPI — прямое использование.
- Фронтенд: нативный WebAuthn API в браузере + утилиты для base64url ↔ ArrayBuffer.

Пример зависимостей (pip):

```
pip install python-fido2
# или
pip install webauthn
```

---

## 5. Требования к окружению

- Только HTTPS (в продакшене). Для разработки используйте dev‑сертификат или `localhost` (браузеры делают исключение для WebAuthn на `https` и некоторых случаях для `http://localhost`).
- RP ID (relying party ID) — домен без порта, должен совпадать с origin вашего фронтенда. Пример: для `https://admin.example.com` RP ID = `admin.example.com`.

---

## 6. Эндпоинты API (общее)

Рекомендуемые минимальные маршруты:

- POST `/webauthn/register/options` — сгенерировать `challenge` и `PublicKeyCredentialCreationOptions`.
- POST `/webauthn/register/verify` — принять ответ от `navigator.credentials.create`, верифицировать, сохранить credential.
- POST `/webauthn/login/options` — сгенерировать `challenge` и `PublicKeyCredentialRequestOptions` с `allowCredentials`.
- POST `/webauthn/login/verify` — принять ответ от `navigator.credentials.get`, верифицировать подпись, установить сессию/выдать токен.

Сессии храните в HttpOnly Secure cookie (для SSR) или верните короткоживущий токен (для SPA). Ограничьте доступ к `/admin/*` middleware‑ом.

---

## 7. Фронтенд (ядро WebAuthn)

Вам понадобятся функции преобразования:

```js
// base64url ↔ ArrayBuffer
function bufferToBase64url(buffer) {
  const bytes = new Uint8Array(buffer);
  let binary = '';
  for (let i = 0; i < bytes.byteLength; i++) binary += String.fromCharCode(bytes[i]);
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/g, '');
}

function base64urlToBuffer(base64url) {
  const pad = '='.repeat((4 - (base64url.length % 4)) % 4);
  const base64 = (base64url + pad).replace(/-/g, '+').replace(/_/g, '/');
  const raw = atob(base64);
  const bytes = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) bytes[i] = raw.charCodeAt(i);
  return bytes.buffer;
}
```

Регистрация ключа (упрощённый пример):

```js
// 1) Получить options от сервера
const creationOptions = await fetch('/webauthn/register/options', { method: 'POST', credentials: 'include' })
  .then(r => r.json());

// 2) Преобразовать бинарные поля из base64url в ArrayBuffer
creationOptions.publicKey.user.id = base64urlToBuffer(creationOptions.publicKey.user.id);
creationOptions.publicKey.challenge = base64urlToBuffer(creationOptions.publicKey.challenge);
if (creationOptions.publicKey.excludeCredentials) {
  creationOptions.publicKey.excludeCredentials = creationOptions.publicKey.excludeCredentials.map(c => ({
    ...c,
    id: base64urlToBuffer(c.id)
  }));
}

// 3) Вызвать WebAuthn
const credential = await navigator.credentials.create(creationOptions);

// 4) Подготовить ответ для сервера
const attestationResponse = {
  id: credential.id,
  rawId: bufferToBase64url(credential.rawId),
  type: credential.type,
  response: {
    attestationObject: bufferToBase64url(credential.response.attestationObject),
    clientDataJSON: bufferToBase64url(credential.response.clientDataJSON)
  }
};

// 5) Отправить на верификацию
await fetch('/webauthn/register/verify', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  credentials: 'include',
  body: JSON.stringify(attestationResponse)
});
```

Вход по ключу:

```js
// 1) Получить options
const requestOptions = await fetch('/webauthn/login/options', { method: 'POST', credentials: 'include' })
  .then(r => r.json());

// 2) Конвертация бинарных полей
requestOptions.publicKey.challenge = base64urlToBuffer(requestOptions.publicKey.challenge);
if (requestOptions.publicKey.allowCredentials) {
  requestOptions.publicKey.allowCredentials = requestOptions.publicKey.allowCredentials.map(c => ({
    ...c,
    id: base64urlToBuffer(c.id)
  }));
}

// 3) WebAuthn
const assertion = await navigator.credentials.get(requestOptions);

// 4) Ответ серверу
const assertionResponse = {
  id: assertion.id,
  rawId: bufferToBase64url(assertion.rawId),
  type: assertion.type,
  response: {
    authenticatorData: bufferToBase64url(assertion.response.authenticatorData),
    clientDataJSON: bufferToBase64url(assertion.response.clientDataJSON),
    signature: bufferToBase64url(assertion.response.signature),
    userHandle: assertion.response.userHandle ? bufferToBase64url(assertion.response.userHandle) : null
  }
};

await fetch('/webauthn/login/verify', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  credentials: 'include',
  body: JSON.stringify(assertionResponse)
});
```

---

## 8. Пример реализации: Django

### 8.1. Установка

```
pip install django python-fido2
```

### 8.2. Настройки `settings.py`

- `INSTALLED_APPS`: ваш app, с моделями `User`/`WebAuthnCredential`.
- Конфигурация сессий и CSRF.
- Константы WebAuthn:
  - `WEBAUTHN_RP_ID = 'admin.example.com'`
  - `WEBAUTHN_RP_NAME = 'My Admin Panel'`

### 8.3. Миграции и модели

Создайте модель `WebAuthnCredential` с полями из раздела 3, FK на пользователя. Выполните миграции.

### 8.4. Views (контуры)

- `register_options_view(request)`:
  - Проверить, что пользователь авторизован и имеет право привязывать ключ (или процесс первичной инициализации).
  - Сгенерировать `challenge` (случайные bytes), сохранить в сессии.
  - Собрать `PublicKeyCredentialCreationOptions`:
    - `rp` = { id: RP_ID, name: RP_NAME }
    - `user` = { id: user.id (bytes), name: user.username, displayName: user.get_full_name() }
    - `pubKeyCredParams` (например, [{ type: 'public-key', alg: -7 }, { alg: -257 }])
    - `timeout`, `attestation`, `excludeCredentials` (существующие credential_id)
  - Возвратить JSON с base64url строками.

- `register_verify_view(request)`:
  - Принять `attestationObject`, `clientDataJSON` и т. п.
  - С помощью `python-fido2`/`webauthn` верифицировать аттестацию и извлечь `credential_id`, `public_key`, `sign_count`.
  - Сохранить credential в БД.

- `login_options_view(request)`:
  - По логину/пользователю найти credentials.
  - Сгенерировать `challenge`, сохранить в сессии.
  - Вернуть `PublicKeyCredentialRequestOptions` с `allowCredentials`.

- `login_verify_view(request)`:
  - Принять `authenticatorData`, `clientDataJSON`, `signature`, `rawId`.
  - Найти credential по `rawId`/`credential_id`, верифицировать подпись.
  - Обновить `sign_count` (проверить монотонность), установить сессию.

- Защитить админ‑маршруты декораторами `@login_required` и проверками `request.user.is_staff`/`is_superuser`.

### 8.5. URL‑маршрутизация

Добавьте пути в `urls.py` к четырём эндпоинтам + ваши админ‑вьюхи.

### 8.6. Шаблоны

Страницы: «Привязка ключа», «Вход по ключу», «Список ключей администратора» (добавление/удаление), подключение JS из раздела 7.

---

## 9. Пример реализации: FastAPI

### 9.1. Установка

```
pip install fastapi uvicorn python-fido2
```

### 9.2. Контуры роутинга

- POST `/webauthn/register/options`: генерирует options, кладёт `challenge` в серверное хранилище сессий (Redis/в памяти, если одна реплика) привязанное к пользователю.
- POST `/webauthn/register/verify`: верифицирует и сохраняет credential.
- POST `/webauthn/login/options`: по пользователю ищет credentials, генерирует `challenge`.
- POST `/webauthn/login/verify`: верифицирует подпись, выдаёт строгий cookie‑токен/сессию.
- Зависимости FastAPI для защиты `/admin/*` (проверка токена и роли).

### 9.3. Сессии и куки

- HttpOnly + Secure + SameSite=Strict.
- Короткий TTL токена, ротация, серверная чёрная метка при logout (опционально).

---

## 10. Безопасность (чеклист)

- HTTPS везде. Корректный RP ID.
- Защита сессии: HttpOnly, Secure, SameSite=Strict. CSRF для state‑изменяющих запросов при cookie‑сессии.
- Rate limiting по логину и IP.
- Журналы: привязка/удаление ключей, входы, IP/UA, изменения прав.
- Политика ключей: разрешайте несколько ключей; именование устройств; удаление/восстановление.
- Sign Counter: проверять монотонность, при регрессе расследовать/блокировать credential.
- Политика восстановления: одноразовые резервные коды, break‑glass процедура (раздельный канал связи).
- CORS: если SPA на другом домене — настраивайте CORS осторожно.
- Content Security Policy (CSP) для фронтенда.

---

## 11. Альтернатива: mTLS (клиентские сертификаты)

- Настроить Nginx/Traefik для запроса клиентского сертификата: `ssl_verify_client on;`
- Выпустить CA → админский сертификат; установить на устройство администратора.
- Прокинуть атрибуты сертификата в бэкенд через заголовки (только если trust boundary корректен) или через переменные.
- Плюсы: просто верифицировать на периметре. Минусы: сложнее UX, доставка сертификатов, мобильные устройства.

---

## 12. Тестирование

- Окружения: Windows Hello, macOS Touch ID/Passkeys, Android, YubiKey (USB/NFC/BLE).
- Сценарии:
  - Регистрация первого ключа администратора.
  - Вход тем же ключом, проверка `sign_count`.
  - Привязка второго ключа, удаление первого.
  - Попытка входа с неверным ключом.
  - Потеря ключа → восстановление (резервные коды/супер‑админ).

---

## 13. Типовые ошибки и отладка

- `NotAllowedError`: пользователь отменил операцию или таймаут — увеличьте timeout на сервере и в options.
- `SecurityError`/`InvalidStateError`: неверный RP ID / несоответствие origin.
- Неверная подпись: убедитесь в корректной конвертации base64url ↔ ArrayBuffer; проверьте `clientDataJSON.type` (`webauthn.create`/`webauthn.get`).
- Проблемы с `user.id`: это `bytes` (стабильный идентификатор), не строка.
- `sign_count` уменьшился: вероятное клонирование/сброс устройства — заблокируйте credential и потребуйте повторную регистрацию.

---

## 14. Порядок внедрения (за 1–2 дня)

1) Выбрать стек (Django или FastAPI).  
2) Добавить зависимости: `python-fido2` (или `webauthn`).  
3) Смоделировать БД и миграции для `WebAuthnCredential`.  
4) Реализовать 4 эндпоинта (options/verify для регистрации и логина).  
5) Реализовать минимальный фронтенд на HTML+JS (см. раздел 7).  
6) Защитить `/admin/*` ролью и сессией/токеном.  
7) Настроить HTTPS и корректный RP ID.  
8) Покрыть rate limiting и журналирование.  
9) Протестировать на 2–3 платформах/ключах.  

---

## 15. Примечания по хранению

- Храните `credential_id` и `public_key` в двоичном виде или base64url. Индексируйте `credential_id`.
- Не храните приватные ключи. Никогда.
- Для нескольких ключей на пользователя — уникальность по паре (`user_id`, `credential_id`).

---

## 16. Полезные ссылки

- Спецификация WebAuthn: https://www.w3.org/TR/webauthn-3/
- Yubico python-fido2: https://github.com/Yubico/python-fido2
- Duo Labs webauthn (Python): https://github.com/duo-labs/py_webauthn
- Passkeys UX рекомендации: https://developers.google.com/identity/passkeys

---

## 17. Дальшие шаги

- Интеграция в текущий проект: добавить модели, миграции и эндпоинты.
- Написать e2e‑тесты (Playwright/Cypress) для сценариев регистрации и входа.
- Подготовить процедуры восстановления и админскую страницу управления ключами.

Если нужно, я могу добавить каркас (эндпоинты и модели) под ваш стек и обновить `requirements.txt`. Уточните, что используете — Django или FastAPI — и какое доменное имя будет у админ‑панели (для RP ID).

---

## 18. Интеграция в текущий проект (FastAPI + PostgreSQL, редактирование БД через веб)

Контекст проекта: веб‑интерфейс на FastAPI (`src/webapp/server.py`) сейчас защищён HTTP Basic. Планируется редактирование БД из веб‑интерфейса, поэтому требуется более сильная аутентификация и дополнительные меры безопасности.

### 18.1. Цели
- Заменить HTTP Basic на сессионную аутентификацию с WebAuthn (Passkeys) для админ‑панели.
- Добавить безопасные CRUD‑операции по таблицам БД (в первую очередь `articles`, `dlq`) с аудитом изменений и защитой от конфликтов.

### 18.2. Зависимости и конфигурация
- Добавить зависимость:
  - `python-fido2` (или альтернатива `webauthn`).
  - Обновить `requirements.txt` и пересобрать Docker‑образ.
- Конфигурация окружения (`.env`):
  - `WEB_AUTH_MODE=webauthn` (режим аутентификации: `basic|webauthn`; на время миграции — `basic`/гибрид, затем `webauthn`).
  - `WEB_SESSION_SECRET=<длинный_секрет>` — секрет для сессий.
  - `WEB_RP_ID=<домен_админки>` — RP ID для WebAuthn (например, `admin.example.com`).
  - `WEB_COOKIE_TTL=3600` — TTL сессии в секундах (пример).
  - TLS/прокси: обеспечить HTTPS на внешнем уровне (Traefik/Nginx/Caddy) для домена RP ID.

### 18.3. Изменения на сервере FastAPI
- Подключить сессии (Starlette `SessionMiddleware`) в `src/webapp/server.py`:
  - HttpOnly, Secure, `SameSite=Strict`, TTL из `WEB_COOKIE_TTL`.
- Охрана маршрутов:
  - Ввести префикс `/admin/*` для защищённых UI/CRUD.
  - Заменить текущую проверку HTTP Basic на проверку сессии (присутствие и валидность сессионного признака администратора).
  - Оставить временно BasicAuth как fallback при `WEB_AUTH_MODE=basic` до завершения онбординга ключей.
- Эндпоинты WebAuthn (см. разделы 6 и 9):
  - POST `/webauthn/register/options`, `/webauthn/register/verify`.
  - POST `/webauthn/login/options`, `/webauthn/login/verify`.
- Хранить `challenge` в сессии на время операции; для нескольких админов — можно в Redis или в БД с TTL.
- CSRF‑защита:
  - Для всех state‑изменяющих форм/запросов `/admin/*` добавить CSRF‑токен (double‑submit cookie + заголовок, или собственная middleware).

### 18.4. Схема БД (PostgreSQL) — новые таблицы
- Таблица учётных данных WebAuthn (минималистичная):
```sql
CREATE TABLE IF NOT EXISTS webauthn_credential (
  id BIGSERIAL PRIMARY KEY,
  user_id TEXT NOT NULL,
  credential_id BYTEA NOT NULL UNIQUE,
  public_key BYTEA NOT NULL,
  sign_count INTEGER NOT NULL DEFAULT 0,
  transports TEXT,
  aaguid TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  last_used_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_webauthn_user ON webauthn_credential (user_id);
```
- Журнал аудита изменений:
```sql
CREATE TABLE IF NOT EXISTS audit_log (
  id BIGSERIAL PRIMARY KEY,
  actor TEXT NOT NULL,
  action TEXT NOT NULL,
  entity TEXT NOT NULL,
  entity_id TEXT,
  before_json TEXT,
  after_json TEXT,
  ip TEXT,
  user_agent TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_audit_entity ON audit_log (entity, entity_id);
```
Примечание: для single‑admin можно использовать фиксированный `user_id='admin'`. При расширении — добавить таблицу `user` с флагом роли.

### 18.5. Админ‑CRUD (редактирование БД)
- `articles`:
  - Формы редактирования: `title`, `content`, `summary_text`, `published_at`.
  - Soft‑delete: поле `deleted_at` (опционально) вместо физического удаления.
  - При изменении `content` пересчитывать `content_hash` и обновлять `updated_at`.
- `dlq`:
  - Просмотр, удаление записей; (опционально) повторная обработка.
- Общие требования к записям изменений:
  - Каждую операцию записывать в `audit_log` (до/после в JSON, actor из сессии, IP/UA из запроса).
  - Валидация входных данных, ограничение длины полей, экранирование HTML при выводе.
- Защита от конфликтов:
  - Добавить/использовать столбец `updated_at` для оптимистической блокировки: при сохранении проверять, что `updated_at` не изменился; при конфликте — показать предупреждение и предложить_merge/повтор.

### 18.6. Эксплуатационные меры для PostgreSQL
- Все операции записи выполнять в явных транзакциях там, где нужно согласованное состояние.
- Перед деструктивными действиями (массовые удаления) — делайте логический бэкап (pg_dump) и используйте `tools/backup.py`.
- Следить за индексами и планами запросов (EXPLAIN ANALYZE) для интерфейсов редактирования.

### 18.7. Безопасность
- Только HTTPS, корректный RP ID.
- Сессии: HttpOnly, Secure, `SameSite=Strict`, короткий TTL и ротация токена после логина.
- CSRF для POST/PUT/DELETE под `/admin/*`.
- Rate limiting на `/webauthn/*` и чувствительные операции админки.
- Строгий CSP (уже настроен в middleware) — сохранить.
- Регистрация минимум двух ключей на администратора; процедура восстановления (backup‑коды или break‑glass через изолированный канал).

### 18.8. Порядок внедрения (в проект)
1) Добавить `python-fido2` в зависимости и пересобрать Docker‑образ.
2) Включить `SessionMiddleware` и режим `WEB_AUTH_MODE=basic` (гибрид) — админка пока работает по BasicAuth.
3) Реализовать 4 эндпоинта WebAuthn и страницы/JS из раздела 7.
4) Привязать минимум два ключа для администратора.
5) Включить CSRF, аудит.
6) Переключить `WEB_AUTH_MODE=webauthn`, отключить BasicAuth.
7) Пробные изменения в БД через админ‑формы; проверить `audit_log` и конфликты `updated_at`.

### 18.9. Тестирование (проект)
- Unit/интеграционные тесты CRUD админки (успех/валидации/конфликты/аудит).
- E2E (Playwright): регистрация ключа, вход, редактирование статьи, конфликт правки, отмена/возврат.
- Smoke: конкурентная работа бота и админки (проверка блокировок и WAL), отсутствие deadlock‑ов.

### 18.10. Критерии готовности (DoD)
- WebAuthn‑вход работает на минимум двух платформах (например, Windows Hello и YubiKey) и с двумя ключами на админа.
- Админ‑маршруты доступны только при валидной сессии; BasicAuth отключён.
- Все CRUD‑операции пишут аудит с до/после.
- Конкурентные конфликты корректно обрабатываются (оптимистическая блокировка).
- Тесты зелёные; проведено e2e.

### 18.11. Риски и смягчения (проект)
- Несовпадение RP ID ↔ origin: тщательно проверить конфиг RP и домен/поддомен.
- Потеря всех ключей: иметь документированную break‑glass процедуру (выдача временной mTLS‑доступа или одноразового токена на ограниченное время).
- Конкурентные записи: использовать короткие транзакции, разумные уровни изоляции и идемпотентность операций.

