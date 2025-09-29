import pytest
from datetime import date
from unittest.mock import patch, MagicMock
from src.webapp.services import get_month_calendar_data

# Тесты для маршрута /calendar
from fastapi.testclient import TestClient
from src.webapp.server import app  # предполагаем, что сервер FastAPI доступен


class TestGetMonthCalendarData:
    """Тесты для функции get_month_calendar_data в services.py"""

    def test_get_month_calendar_data_current_month(self):
        """Тест получения данных календаря для текущего месяца"""
        today = date.today()
        year = today.year
        month = today.month

        result = get_month_calendar_data(year, month)

        # Проверяем основные ключи в результате
        assert 'year' in result
        assert 'month' in result
        assert 'weeks' in result
        assert 'prev' in result
        assert 'next' in result
        
        # Проверяем значения года и месяца
        assert result['year'] == year
        assert result['month'] == month
        
        # Проверяем структуру weeks
        assert isinstance(result['weeks'], list)
        assert len(result['weeks']) > 0
        
        # Проверяем структуру недель и дней
        for week in result['weeks']:
            assert 'days' in week
            assert 'total' in week
            assert 'summarized' in week
            assert 'all_summarized' in week
            
            for day in week['days']:
                assert 'date' in day
                assert 'day' in day
                assert 'in_month' in day
                assert 'total' in day
                assert 'summarized' in day

    def test_get_month_calendar_data_specific_month(self):
        """Тест получения данных календаря для конкретного месяца"""
        year = 2023
        month = 3  # Март

        result = get_month_calendar_data(year, month)

        assert result['year'] == year
        assert result['month'] == month
        assert isinstance(result['weeks'], list)
        
        # Проверяем, что в марте 2023 есть 5 недель
        assert len(result['weeks']) == 5

    def test_get_month_calendar_data_prev_next_months(self):
        """Тест получения данных о предыдущем и следующем месяцах"""
        # Тестируем март 2023
        result = get_month_calendar_data(2023, 3)

        assert result['prev'] == {'year': 2023, 'month': 2}  # Февраль
        assert result['next'] == {'year': 2023, 'month': 4}  # Апрель

    def test_get_month_calendar_data_year_boundary(self):
        """Тест перехода через границу года"""
        # Тестируем декабрь
        result = get_month_calendar_data(2023, 12)

        assert result['prev'] == {'year': 2023, 'month': 11}  # Ноябрь
        assert result['next'] == {'year': 2024, 'month': 1}   # Январь следующего года

        # Тестируем январь
        result = get_month_calendar_data(2023, 1)

        assert result['prev'] == {'year': 2022, 'month': 12}  # Декабрь предыдущего года
        assert result['next'] == {'year': 2023, 'month': 2}   # Февраль

    def test_get_month_calendar_data_fallback(self):
        """Тест сценария с fallback при проблемах с БД"""
        with patch('src.webapp.services.get_db_connection') as mock_conn:
            # Симулируем ошибку подключения к БД
            mock_conn.side_effect = Exception("Database connection failed")
            
            result = get_month_calendar_data(2023, 3)

            # Проверяем, что fallback сработал и вернул базовую структуру
            assert result['year'] == 2023
            assert result['month'] == 3
            assert isinstance(result['weeks'], list)
            assert len(result['weeks']) > 0
            
            # Проверяем, что все дни имеют нулевые значения
            for week in result['weeks']:
                for day in week['days']:
                    assert day['total'] == 0
                    assert day['summarized'] == 0

    def test_get_month_calendar_data_with_data(self):
        """Тест получения данных календаря с реальными данными из БД"""
        # Используем реальное подключение к БД (если доступно)
        # или мокаем для тестирования логики агрегации
        
        # Тестируем с текущим месяцем
        today = date.today()
        result = get_month_calendar_data(today.year, today.month)
        
        # Проверяем, что структура правильная
        assert 'year' in result
        assert 'month' in result
        assert 'weeks' in result
        
        # Проверяем, что дни имеют правильные свойства
        for week in result['weeks']:
            for day in week['days']:
                assert isinstance(day['date'], str)
                assert isinstance(day['day'], int)
                assert isinstance(day['in_month'], bool)
                assert isinstance(day['total'], int)
                assert isinstance(day['summarized'], int)
                
                # Проверяем формат даты
                assert len(day['date']) == 10 # YYYY-MM-DD
                assert day['total'] >= 0
                assert day['summarized'] >= 0
                assert day['summarized'] <= day['total']

    def test_get_month_calendar_data_all_summarized_flag(self):
        """Тест флага all_summarized в неделях"""
        today = date.today()
        result = get_month_calendar_data(today.year, today.month)
        
        # Проверяем, что флаг all_summarized присутствует имеет правильный тип
        for week in result['weeks']:
            assert 'all_summarized' in week
            assert isinstance(week['all_summarized'], bool)
            
            # Проверяем логику флага: all_summarized = (total > 0 && total == summarized)
            if week['total'] > 0:
                expected = week['total'] == week['summarized']
                assert week['all_summarized'] == expected
            else:
                # Если total = 0, то all_summarized должен быть False
                assert not week['all_summarized']


# Тесты для маршрута /calendar
from fastapi.testclient import TestClient
import os
from src.webapp.server import app  # предполагаем, что сервер FastAPI доступен


class TestCalendarRoute:
    """Тесты для маршрута /calendar в routes_articles.py"""
    
    def setup_method(self):
        # Устанавливаем переменные окружения для обхода аутентификации в тестах
        os.environ["WEB_BASIC_AUTH_USER"] = "test"
        os.environ["WEB_BASIC_AUTH_PASSWORD"] = "test"
        self.client = TestClient(app)
    
    def teardown_method(self):
        # Восстанавливаем переменные окружения после тестов
        if "WEB_BASIC_AUTH_USER" in os.environ:
            del os.environ["WEB_BASIC_AUTH_USER"]
        if "WEB_BASIC_AUTH_PASSWORD" in os.environ:
            del os.environ["WEB_BASIC_AUTH_PASSWORD"]
    
    def test_calendar_route_get_request(self):
        """Тест GET-запроса к маршруту /calendar"""
        # Сначала залогинимся, чтобы обойти аутентификацию
        login_response = self.client.post("/basic-login", data={"username": "test", "password": "test"})
        assert login_response.status_code in [303, 200]  # Редирект или успешный логин
        
        # Теперь делаем запрос к календарю
        response = self.client.get("/calendar")
        
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
    
    def test_calendar_route_with_year_month_params(self):
        """Тест маршрута /calendar с параметрами года и месяца"""
        # Сначала залогинимся
        self.client.post("/basic-login", data={"username": "test", "password": "test"})
        
        response = self.client.get("/calendar?year=2023&month=3")
        
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
    
    def test_calendar_route_with_fragment_param(self):
        """Тест маршрута /calendar с параметром fragment для получения HTML-фрагмента"""
        # Сначала залогинимся
        self.client.post("/basic-login", data={"username": "test", "password": "test"})
        
        response = self.client.get("/calendar?year=2023&month=3&fragment=1")
        
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
    
    def test_calendar_route_current_month_default(self):
        """Тест маршрута /calendar без параметров (должен вернуть текущий месяц)"""
        # Сначала залогинимся
        self.client.post("/basic-login", data={"username": "test", "password": "test"})
        
        response = self.client.get("/calendar")
        
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
    
    def test_calendar_route_invalid_year_month(self):
        """Тест маршрута /calendar с некорректными параметрами года и месяца"""
        # Сначала залогинимся
        self.client.post("/basic-login", data={"username": "test", "password": "test"})
        
        # Тестируем с некорректным месяцем
        response = self.client.get("/calendar?year=2023&month=13")
        
        # Должен обработать ошибку корректно, не вызвав исключение
        assert response.status_code in [200, 400, 500]  # Может вернуть 200 с пустым календарем или ошибку
    
    def test_calendar_route_response_structure(self):
        """Тест структуры ответа маршрута /calendar"""
        # Сначала залогинимся
        self.client.post("/basic-login", data={"username": "test", "password": "test"})
        
        response = self.client.get("/calendar")
        
        assert response.status_code == 200
        content = response.text
        # Проверяем наличие основных элементов HTML календаря
        assert "<div" in content # Должны быть HTML-элементы
        assert "calendar" in content.lower()  # Должно содержать слово calendar в классах или id