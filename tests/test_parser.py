import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime
from zoneinfo import ZoneInfo

# Добавляем путь к src в sys.path для импорта
from src.parser import get_articles_from_page, get_article_text, _parse_custom_date

# Определяем таймзону для тестов, чтобы они не зависили от системной
APP_TZ = ZoneInfo("Europe/Moscow")

# --- Фикстуры и моки ---

@pytest.fixture
def mock_requests_get():
    """Фикстура для мока requests.get."""
    with patch('src.parser.requests.get') as mock_get:
        yield mock_get

@pytest.fixture
def mock_news_list_html():
    """HTML-контент для списка новостей с разными форматами дат."""
    html = """
    <html>
        <head>
            <meta http-equiv="content-type" content="text/html; charset=windows-1251">
        </head>
        <body>
            <table border="0" align="center" cellspacing="0" width="100%">
                <tr><td class="topic_caption"><a href="/news/2025/8/4/article1.html">Заголовок 1</a></td></tr>
                <tr><td class="topic_info_top">04.08.25 12:00</td></tr>
            </table>
            <table border="0" align="center" cellspacing="0" width="100%">
                <tr><td class="topic_caption"><a href="/news/2024/8/4/article2.html">Заголовок 2</a></td></tr>
                <tr><td class="topic_info_top">04.08.2024 13:00</td></tr>
            </table>
        </body>
    </html>
    """
    return html.encode('windows-1251')

@pytest.fixture
def mock_article_html():
    """HTML-контент для полной статьи."""
    html = """
    <html>
        <body>
            <td class="topic_text">
                <script>console.log("script content")</script>
                <style>.bold {font-weight: bold;}</style>
                <p>Это полный текст статьи.</p>
                Еще немного текста.
            </td>
        </body>
    </html>
    """
    return html.encode('windows-1251')

# --- Тесты для _parse_custom_date ---

def test_parse_custom_date_short_year():
    """Тест парсинга даты с 2-значным годом."""
    dt = _parse_custom_date("04.08.25 12:00")
    expected_dt = datetime(2025, 8, 4, 12, 0, tzinfo=APP_TZ)
    assert dt == expected_dt

def test_parse_custom_date_long_year():
    """Тест парсинга даты с 4-значным годом."""
    dt = _parse_custom_date("04.08.2024 13:00")
    expected_dt = datetime(2024, 8, 4, 13, 0, tzinfo=APP_TZ)
    assert dt == expected_dt

def test_parse_custom_date_invalid_format():
    """Тест на неверный формат даты."""
    with pytest.raises(ValueError):
        _parse_custom_date("2024-08-04 13:00")

# --- Тесты для get_articles_from_page ---

def test_get_articles_from_page_success(mock_requests_get, mock_news_list_html):
    """
    Тест успешного парсинга списка статей с разными форматами дат.
    """
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.content = mock_news_list_html
    mock_response.encoding = 'windows-1251'
    # Явно задаем .text, чтобы избежать ошибки кодировки в тесте
    mock_response.text = mock_news_list_html.decode('windows-1251')
    mock_requests_get.return_value = mock_response

    articles = get_articles_from_page(page=1)

    assert len(articles) == 2
    assert articles[0]['title'] == "Заголовок 1"
    assert articles[0]['link'] == "https://www.warandpeace.ru/news/2025/8/4/article1.html"
    assert articles[0]['published_at'] == datetime(2025, 8, 4, 12, 0, tzinfo=APP_TZ)
    assert articles[1]['title'] == "Заголовок 2"
    assert articles[1]['link'] == "https://www.warandpeace.ru/news/2024/8/4/article2.html"
    assert articles[1]['published_at'] == datetime(2024, 8, 4, 13, 0, tzinfo=APP_TZ)

# --- Тесты для get_article_text ---

def test_get_article_text_success(mock_requests_get, mock_article_html):
    """
    Тест успешного извлечения полного текста статьи.
    """
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.content = mock_article_html
    mock_response.encoding = 'windows-1251'
    # Явно задаем .text
    mock_response.text = mock_article_html.decode('windows-1251')
    mock_requests_get.return_value = mock_response

    text = get_article_text("http://example.com/article")

    assert "Это полный текст статьи." in text
    assert "Еще немного текста." in text
    assert "script content" not in text
    assert "font-weight" not in text