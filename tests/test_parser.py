import pytest
import requests
from unittest.mock import patch, MagicMock
from bs4 import BeautifulSoup
from datetime import date

# Добавляем путь к src в sys.path для импорта
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))

from parser import get_articles_from_page, get_article_text

# --- Фикстуры и моки ---

@pytest.fixture
def mock_requests_get():
    """Фикстура для мока requests.get."""
    with patch('parser.requests.get') as mock_get:
        yield mock_get

@pytest.fixture
def mock_news_list_html():
    """HTML-контент для списка новостей в кодировке windows-1251."""
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
                <tr><td class="topic_caption"><a href="/news/2025/8/4/article2.html">Заголовок 2</a></td></tr>
                <tr><td class="topic_info_top">04.08.25 13:00</td></tr>
            </table>
        </body>
    </html>
    """
    return html.encode('windows-1251')

@pytest.fixture
def mock_article_html():
    """HTML-контент для полной статьи."""
    return """
    <html>
        <body>
            <div class="ni_text">
                <script>console.log("script content")</script>
                <style>.bold {font-weight: bold;}</style>
                <p>Это полный текст статьи.</p>
                Еще немного текста.
            </div>
        </body>
    </html>
    """

# --- Тесты для get_articles_from_page ---

def test_get_articles_from_page_success(mock_requests_get, mock_news_list_html):
    """
    Тест успешного парсинга списка статей.
    """
    # Настройка мока
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.content = mock_news_list_html
    mock_response.text = mock_news_list_html.decode('windows-1251')
    # response.text будет автоматически декодирован mock'ом, если указать encoding
    mock_response.encoding = 'windows-1251'
    mock_requests_get.return_value = mock_response

    # Вызов функции
    articles = get_articles_from_page(page=1)

    # Проверки
    assert len(articles) == 2
    assert articles[0]['title'] == "Заголовок 1"
    assert articles[0]['link'] == "https://www.warandpeace.ru/news/2025/8/4/article1.html"
    assert articles[0]['date'] == date.today()
    assert articles[0]['time'] == "04.08.25 12:00"
    assert articles[1]['title'] == "Заголовок 2"

def test_get_articles_from_page_network_error(mock_requests_get):
    """
    Тест обработки сетевой ошибки при получении списка статей.
    """
    # Настройка мока
    mock_requests_get.side_effect = requests.exceptions.RequestException("Network Error")

    # Вызов функции
    articles = get_articles_from_page(page=1)

    # Проверка
    assert articles == []

def test_get_articles_from_page_empty(mock_requests_get):
    """
    Тест обработки пустой страницы без новостей.
    """
    # Настройка мока
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = "<html><body></body></html>"
    mock_requests_get.return_value = mock_response

    # Вызов функции
    articles = get_articles_from_page(page=1)

    # Проверка
    assert articles == []

# --- Тесты для get_article_text ---

def test_get_article_text_success(mock_requests_get, mock_article_html):
    """
    Тест успешного извлечения полного текста статьи.
    """
    # Настройка мока
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = mock_article_html
    mock_response.encoding = 'utf-8'
    mock_requests_get.return_value = mock_response

    # Вызов функции
    text = get_article_text("http://example.com/article")

    # Проверки
    assert "Это полный текст статьи." in text
    assert "Еще немного текста." in text
    assert "script content" not in text  # Убедимся, что скрипты и стили удалены
    assert "font-weight" not in text

def test_get_article_text_content_not_found(mock_requests_get):
    """
    Тест случая, когда блок с текстом статьи не найден.
    """
    # Настройка мока
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = "<html><body><div class='wrong_class'></div></body></html>"
    mock_requests_get.return_value = mock_response

    # Вызов функции
    text = get_article_text("http://example.com/article")

    # Проверка
    assert text is None

def test_get_article_text_network_error(mock_requests_get):
    """
    Тест обработки сетевой ошибки при получении текста статьи.
    """
    # Настройка мока
    mock_requests_get.side_effect = requests.exceptions.RequestException("Network Error")

    # Вызов функции
    text = get_article_text("http://example.com/article")

    # Проверка
    assert text is None