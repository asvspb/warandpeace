import asyncio
import pytest
from click.testing import CliRunner
from unittest.mock import patch, MagicMock

from scripts.manage import cli


@pytest.fixture(autouse=True)
def mock_init_db():
    with patch('scripts.manage.init_db') as mock:
        yield mock


def run_cli(args):
    runner = CliRunner()
    return runner.invoke(cli, args)


@patch('scripts.manage.get_dlq_size', return_value=0)
@patch('scripts.manage.upsert_raw_article')
@patch('scripts.manage.get_article_text', return_value='CONTENT')
@patch('scripts.manage.get_articles_from_page')
def test_ingest_page_success(mock_list, mock_get_text, mock_upsert, mock_dlq_size):
    mock_list.return_value = [
        {'link': 'https://example.com/a', 'title': 'A', 'published_at': '2025-08-04T12:00:00'},
        {'link': 'https://example.com/b', 'title': 'B', 'published_at': '2025-08-04T12:01:00'},
    ]
    result = run_cli(['ingest-page', '--page', '1', '--limit', '2'])
    assert result.exit_code == 0, result.output
    assert 'Добавлено/обновлено: 2' in result.output
    assert mock_upsert.call_count == 2


@patch('scripts.manage.get_dlq_size', return_value=1)
@patch('scripts.manage.dlq_record')
@patch('scripts.manage.upsert_raw_article')
@patch('scripts.manage.get_article_text', return_value=None)
@patch('scripts.manage.get_articles_from_page')
def test_ingest_page_dlq(mock_list, mock_get_text, mock_upsert, mock_dlq_record, mock_dlq_size):
    mock_list.return_value = [
        {'link': 'https://example.com/a', 'title': 'A', 'published_at': '2025-08-04T12:00:00'},
    ]
    result = run_cli(['ingest-page', '--page', '1', '--limit', '1'])
    assert result.exit_code == 0, result.output
    assert 'DLQ=1' in result.output
    mock_dlq_record.assert_called_once()


@patch('scripts.manage.upsert_raw_article')
@patch('scripts.manage.get_article_text', return_value='CONTENT')
@patch('scripts.manage.fetch_articles_for_date')
def test_backfill_range_success(mock_fetch_date, mock_get_text, mock_upsert):
    mock_fetch_date.return_value = [('T1', 'https://example.com/a')]
    result = run_cli(['backfill-range', '--from-date', '2025-08-01', '--to-date', '2025-08-02'])
    assert result.exit_code == 0, result.output
    # 2 days * 1 article per day
    assert mock_upsert.call_count == 2


@patch('scripts.manage.upsert_raw_article')
@patch('scripts.manage.get_article_text', return_value='CONTENT')
@patch('scripts.manage.fetch_articles_for_date')
def test_reconcile_success(mock_fetch_date, mock_get_text, mock_upsert):
    mock_fetch_date.return_value = [('T1', 'https://example.com/a')]
    result = run_cli(['reconcile', '--since-days', '1'])
    assert result.exit_code == 0, result.output
    assert mock_upsert.call_count >= 1


@patch('scripts.manage.set_article_summary')
@patch('scripts.manage.summarize', return_value='SUMMARY')
@patch('scripts.manage.list_articles_without_summary_in_range')
def test_summarize_range_success(mock_list, mock_sum, mock_set):
    mock_list.return_value = [
        {'id': 1, 'title': 'T', 'content': 'CONTENT', 'published_at': '2025-08-01 00:00:00'}
    ]
    result = run_cli(['summarize-range', '--from-date', '2025-08-01', '--to-date', '2025-08-02'])
    assert result.exit_code == 0, result.output
    assert 'Суммаризации выполнены: 1' in result.output
    mock_set.assert_called_once()
