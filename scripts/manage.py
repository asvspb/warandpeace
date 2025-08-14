import os
import sys

# --- Настройка путей для корректного импорта ---
# Этот блок должен выполняться перед импортом модулей из src.
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# --- Импорты ---
# Все импорты размещены здесь, после модификации пути,
# чтобы обеспечить корректную загрузку модулей из 'src'.
import logging  # noqa: E402
import asyncio  # noqa: E402
import click  # noqa: E402
from dotenv import load_dotenv  # noqa: E402
from src.database import (  # noqa: E402
    init_db,
    get_articles_for_backfill,
    update_article_backfill_status,
    get_stats,
    upsert_raw_article,
    list_articles_without_summary_in_range,
    set_article_summary,
    dlq_record,
    get_dlq_size,
    list_dlq_items,
    delete_dlq_item,
    get_content_hash_groups,
    list_articles_by_content_hash,
)
from src.database import list_recent_articles  # noqa: E402
from src.parser import get_article_text, get_articles_from_page  # noqa: E402
from src.async_parser import fetch_articles_for_date  # noqa: E402
from src.summarizer import summarize_text_local as summarize  # noqa: E402
from src.url_utils import canonicalize_url  # noqa: E402
from src.metrics import (
    ARTICLES_INGESTED,
    ERRORS_TOTAL,
    DLQ_SIZE,
)

# --- Загрузка переменных окружения ---
dotenv_path = os.path.join(project_root, '.env')
load_dotenv(dotenv_path=dotenv_path)

# --- Настройка и инициализация ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


def _process_articles(articles):
    """Общая логика для обработки списка статей."""
    if not articles:
        click.echo("Нет статей для обработки.")
        return

    total = len(articles)
    click.echo(f"Найдено {total} статей для обработки.")

    with click.progressbar(articles, label='Обработка статей') as bar:
        for article in bar:
            try:
                # 1. Парсинг
                article_text = get_article_text(article['url'])
                if not article_text:
                    raise ValueError("Текст статьи не получен")

                # 2. Суммаризация
                summary = summarize(article_text)
                if not summary:
                    raise ValueError("Резюме не было сгенерировано")

                # 3. Обновление статуса
                update_article_backfill_status(article['id'], 'success', summary)
                logging.info(f"Статья {article['url']} успешно обработана.")

            except Exception as e:
                logging.error(f"Ошибка при обработке статьи {article['url']}: {e}")
                update_article_backfill_status(article['id'], 'failed')


@click.group()
def cli():
    """Инструмент для управления новостным ботом."""
    init_db()
    pass


def _echo_with_dlq_tail(prefix: str) -> None:
    """Печатает строку с добавлением DLQ=SIZE, если возможно.

    Избегает падений в окружениях без прав на каталог БД.
    """
    try:
        dlq_size = get_dlq_size()
        try:
            DLQ_SIZE.set(dlq_size)
        except Exception:
            pass
        click.echo(f"{prefix}; DLQ={dlq_size}")
    except Exception:
        click.echo(prefix)


@cli.command()
@click.option('--force', is_flag=True, help='Запустить без интерактивного подтверждения.')
def backfill(force):
    """
    Заполняет исторические данные для всех необработанных статей.
    """
    if not force:
        # В тестах мы не можем использовать confirm, поэтому добавляем проверку
        if sys.stdin.isatty():
            click.confirm('Вы уверены, что хотите запустить полный backfill? Это может занять много времени.', abort=True)
        else:
            click.echo("Пропущен интерактивный запрос (не в терминале).")

    click.echo("Запуск процесса backfill...")
    articles_to_process = get_articles_for_backfill()
    _process_articles(articles_to_process)
    click.echo("Процесс backfill завершен.")


@cli.command()
def status():
    """Показывает статистику по базе данных."""
    click.echo("Получение статистики...")
    stats = get_stats()
    click.echo("Статистика:")
    click.echo(f"  - Всего статей: {stats.get('total_articles', 0)}")
    click.echo(f"  - Обработано успешно: {stats.get('success', 0)}")
    click.echo(f"  - Ожидает обработки: {stats.get('pending', 0)}")
    click.echo(f"  - Ошибок: {stats.get('failed', 0)}")
    click.echo(f"  - Пропущено: {stats.get('skipped', 0)}")
    last_article = stats.get('last_posted_article', {})
    click.echo(f"  - Последняя статья: \"{last_article.get('title', 'N/A')}\" ({last_article.get('published_at', 'N/A')})")


@cli.command('retry-failed')
@click.option('--force', is_flag=True, help='Запустить без интерактивного подтверждения.')
def retry_failed(force):
    """Повторяет обработку статей, завершившихся с ошибкой."""
    if not force:
        if sys.stdin.isatty():
            click.confirm('Вы уверены, что хотите повторить обработку всех ошибочных статей?', abort=True)
        else:
            click.echo("Пропущен интерактивный запрос (не в терминале).")

    click.echo("Запуск повторной обработки ошибочных статей...")
    failed_articles = get_articles_for_backfill(status='failed')
    _process_articles(failed_articles)
    click.echo("Повторная обработка завершена.")


# --- Новые команды: инжест и суммаризация раздельно ---

@cli.command('ingest-page')
@click.option('--page', type=int, default=1, help='Страница ленты новостей для инжеста.')
@click.option('--limit', type=int, default=10, help='Максимум статей для инжеста за запуск.')
def ingest_page(page: int, limit: int):
    """Загружает «сырые» статьи с указанной страницы и сохраняет content в БД."""
    click.echo(f"Инжест страницы {page} (limit={limit})...")
    articles = get_articles_from_page(page=page)
    added = 0
    for a in articles[:limit]:
        try:
            text = get_article_text(a['link'])
            if not text:
                raise ValueError("Контент пустой")
            upsert_raw_article(a['link'], a['title'], a['published_at'], text)
            added += 1
            ARTICLES_INGESTED.inc()
        except Exception as e:
            logging.error(f"Ошибка инжеста {a['link']}: {e}")
            dlq_record('article', a['link'], error_code=type(e).__name__, error_payload=str(e)[:500])
            ERRORS_TOTAL.labels(type=type(e).__name__).inc()
    _echo_with_dlq_tail(f"Инжест завершён. Добавлено/обновлено: {added}")


@cli.command('backfill-range')
@click.option('--from-date', 'from_date', required=True, help='Начало периода (YYYY-MM-DD)')
@click.option('--to-date', 'to_date', required=True, help='Конец периода (YYYY-MM-DD)')
@click.option('--archive-only', is_flag=True, help='Использовать только архив (быстрее для старых дат).')
@click.option('--max-workers', type=int, default=4, help='Ограничение параллелизма (в разработке: используется последовательная обработка).')
def backfill_range(from_date: str, to_date: str, archive_only: bool, max_workers: int):
    """Backfill «сырых» статей за диапазон дат (без суммаризации)."""
    from datetime import datetime, timedelta
    start = datetime.fromisoformat(from_date).date()
    end = datetime.fromisoformat(to_date).date()
    assert start <= end, "from_date должен быть меньше или равен to_date"

    total_added = 0
    current = start
    while current <= end:
        click.echo(f"Сбор статей за {current.isoformat()}...")
        pairs = asyncio.run(fetch_articles_for_date(current, archive_only=archive_only))
        for title, link in pairs:
            try:
                text = get_article_text(link)
                if not text:
                    raise ValueError("Контент пустой")
                upsert_raw_article(link, title, f"{current} 00:00:00", text)
                total_added += 1
                ARTICLES_INGESTED.inc()
            except Exception as e:
                logging.error(f"Backfill: ошибка для {link}: {e}")
                dlq_record('article', link, error_code=type(e).__name__, error_payload=str(e)[:500])
                ERRORS_TOTAL.labels(type=type(e).__name__).inc()
        current += timedelta(days=1)
    _echo_with_dlq_tail(f"Backfill завершён. Обработано статей: {total_added}")


@cli.command('reconcile')
@click.option('--since-days', type=int, default=7, help='Период к проверке, в днях.')
def reconcile(since_days: int):
    """Сверка последних N дней: сайт vs БД. Загружает недостающее."""
    from datetime import date, timedelta
    today = date.today()
    start = today - timedelta(days=since_days)
    missing_total = 0
    for d in (start + timedelta(days=i) for i in range((today - start).days + 1)):
        pairs = asyncio.run(fetch_articles_for_date(d))
        day_missing = 0
        for title, link in pairs:
            try:
                text = get_article_text(link)
                if not text:
                    raise ValueError("Контент пустой")
                upsert_raw_article(link, title, f"{d} 00:00:00", text)
                day_missing += 1
                ARTICLES_INGESTED.inc()
            except Exception as e:
                logging.error(f"Reconcile: ошибка для {link}: {e}")
                dlq_record('article', link, error_code=type(e).__name__, error_payload=str(e)[:500])
                ERRORS_TOTAL.labels(type=type(e).__name__).inc()
        missing_total += day_missing
        click.echo(f"{d.isoformat()}: дозагружено {day_missing}")
    _echo_with_dlq_tail(f"Reconcile завершён. Дозагружено суммарно: {missing_total}")


@cli.command('summarize-range')
@click.option('--from-date', 'from_date', required=True, help='Начало периода (YYYY-MM-DD)')
@click.option('--to-date', 'to_date', required=True, help='Конец периода (YYYY-MM-DD)')
def summarize_range(from_date: str, to_date: str):
    """Создаёт сводки для статей без резюме за указанный период."""
    start_iso = f"{from_date} 00:00:00"
    end_iso = f"{to_date} 23:59:59"
    rows = list_articles_without_summary_in_range(start_iso, end_iso)
    click.echo(f"Найдено статей без сводки: {len(rows)}")
    done = 0
    for row in rows:
        content = row['content']
        if not content:
            logging.warning(f"Нет контента для статьи id={row['id']}, пропуск")
            continue
        summary = summarize(content)
        if not summary:
            logging.warning(f"Суммаризация не удалась для id={row['id']}")
            continue
        set_article_summary(row['id'], summary)
        done += 1
    click.echo(f"Суммаризации выполнены: {done}")
    # метрики ошибок суммаризации пока опускаем, чтобы не плодить label-cardinality


# --- DLQ: просмотр и повтор ---

@cli.command('dlq-show')
@click.option('--type', 'entity_type', type=click.Choice(['article', 'summary', 'all']), default='all', help='Фильтр по типу сущности')
@click.option('--limit', type=int, default=50, help='Максимум записей к показу')
def dlq_show(entity_type: str, limit: int):
    """Показывает содержимое DLQ."""
    et = None if entity_type == 'all' else entity_type
    items = list_dlq_items(entity_type=et, limit=limit)
    click.echo(f"DLQ записей: {len(items)} (limit={limit})")
    for it in items:
        click.echo(f"- #{it['id']} [{it['entity_type']}] {it['entity_ref']} attempts={it['attempts']} code={it.get('error_code')}")


@cli.command('dlq-retry')
@click.option('--type', 'entity_type', type=click.Choice(['article', 'summary']), default='article', help='Тип сущности для ретрая')
@click.option('--limit', type=int, default=20, help='Максимум элементов для ретрая за запуск')
def dlq_retry(entity_type: str, limit: int):
    """Повторяет обработку элементов из DLQ. Сейчас поддерживаются только статьи."""
    items = list_dlq_items(entity_type=entity_type, limit=limit)
    if not items:
        click.echo("DLQ пуст для заданного фильтра.")
        return
    retried = 0
    succeeded = 0
    for it in items:
        retried += 1
        if it['entity_type'] != 'article':
            # Для summary пока не реализовано
            dlq_record(it['entity_type'], it['entity_ref'], error_code='NotImplemented', error_payload='dlq-retry supports only article for now')
            continue
        link = it['entity_ref']
        try:
            text = get_article_text(link)
            if not text:
                raise ValueError('Контент пустой')
            # В DLQ нет заголовка/даты — в крайнем случае используем сам URL и текущую дату
            title = canonicalize_url(link)
            from datetime import datetime
            published_at = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
            upsert_raw_article(link, title, published_at, text)
            delete_dlq_item(it['id'])
            succeeded += 1
        except Exception as e:
            logging.error(f"DLQ retry error for {link}: {e}")
            dlq_record('article', link, error_code=type(e).__name__, error_payload=str(e)[:500])
    click.echo(f"DLQ retry завершён. Успехов: {succeeded} / попыток: {retried}")


# --- Отчёт по дубликатам контента ---

@cli.command('content-hash-report')
@click.option('--min-count', type=int, default=2, help='Минимальная размерность группы для показа')
@click.option('--details', is_flag=True, help='Показать статьи в каждой группе')
def content_hash_report(min_count: int, details: bool):
    """Показывает группы статей с одинаковым content_hash (возможные дубликаты)."""
    groups = get_content_hash_groups(min_count=min_count)
    if not groups:
        click.echo("Групп дубликатов не найдено.")
        return
    click.echo(f"Найдено групп: {len(groups)} (min_count={min_count})")
    for g in groups:
        h = g['hash']
        cnt = g['cnt']
        click.echo(f"hash={h} cnt={cnt}")
        if details:
            rows = list_articles_by_content_hash(h)
            for r in rows:
                click.echo(f"  - id={r['id']} [{r['published_at']}] {r['title']} ({r['canonical_link']})")


@cli.command('near-duplicates')
@click.option('--days', type=int, default=7, help='Сколько дней анализировать')
@click.option('--limit', type=int, default=200, help='Максимум статей для анализа')
@click.option('--threshold', type=float, default=0.8, help='Порог схожести (0..1)')
def near_duplicates(days: int, limit: int, threshold: float):
    """Быстрый поиск почти-дубликатов по шинглам (Jaccard)."""
    import re
    from collections import defaultdict

    def normalize(text: str) -> list[str]:
        text = text.lower()
        words = re.findall(r"[a-zа-яё0-9]+", text)
        return words

    def shingles(words: list[str], k: int = 5) -> set[tuple[str, ...]]:
        if len(words) < k:
            return set()
        return {tuple(words[i:i+k]) for i in range(len(words) - k + 1)}

    rows = list_recent_articles(days=days, limit=limit)
    sigs: list[tuple[int, str, set[tuple[str, ...]]]] = []
    for r in rows:
        w = normalize(r['content'] or '')
        sh = shingles(w)
        if sh:
            sigs.append((r['id'], r['title'], sh))

    pairs = []
    n = len(sigs)
    for i in range(n):
        for j in range(i + 1, n):
            s1 = sigs[i][2]
            s2 = sigs[j][2]
            inter = len(s1 & s2)
            union = len(s1 | s2)
            if union == 0:
                continue
            jacc = inter / union
            if jacc >= threshold:
                pairs.append((sigs[i][0], sigs[j][0], jacc, sigs[i][1], sigs[j][1]))

    if not pairs:
        click.echo("Почти-дубликаты не найдены")
        return
    pairs.sort(key=lambda x: x[2], reverse=True)
    for a_id, b_id, sim, a_title, b_title in pairs[:200]:
        click.echo(f"{sim:.2f}: id={a_id} ~ id={b_id} | '{a_title}' ~ '{b_title}'")

if __name__ == '__main__':
    cli()
