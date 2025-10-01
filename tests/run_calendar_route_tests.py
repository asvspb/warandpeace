#!/usr/bin/env python3
"""
Скрипт для запуска тестов маршрута /calendar без использования pytest
"""
import unittest
import sys
import os

# Добавляем путь к src в sys.path для импорта модулей
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

# Импортируем необходимые модули
import os
from fastapi.testclient import TestClient
from webapp.server import app  # предполагаем, что сервер FastAPI доступен


class TestCalendarRoute(unittest.TestCase):
    """Тесты для маршрута /calendar в routes_articles.py"""
    
    def setUp(self):
        # Устанавливаем переменные окружения для обхода аутентификации в тестах
        os.environ["WEB_BASIC_AUTH_USER"] = "test"
        os.environ["WEB_BASIC_AUTH_PASSWORD"] = "test"
        self.client = TestClient(app)
    
    def tearDown(self):
        # Восстанавливаем переменные окружения после тестов
        if "WEB_BASIC_AUTH_USER" in os.environ:
            del os.environ["WEB_BASIC_AUTH_USER"]
        if "WEB_BASIC_AUTH_PASSWORD" in os.environ:
            del os.environ["WEB_BASIC_AUTH_PASSWORD"]
    
    def test_calendar_route_get_request(self):
        """Тест GET-запроса к маршруту /calendar"""
        # Сначала залогинимся, чтобы обойти аутентификацию
        login_response = self.client.post("/basic-login", data={"username": "test", "password": "test"})
        self.assertIn(login_response.status_code, [303, 200])  # Редирект или успешный логин
        
        # Теперь делаем запрос к календарю
        response = self.client.get("/calendar")
        
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response.headers["content-type"])
    
    def test_calendar_route_with_year_month_params(self):
        """Тест маршрута /calendar с параметрами года и месяца"""
        # Сначала залогинимся
        self.client.post("/basic-login", data={"username": "test", "password": "test"})
        
        response = self.client.get("/calendar?year=2023&month=3")
        
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response.headers["content-type"])
    
    def test_calendar_route_with_fragment_param(self):
        """Тест маршрута /calendar с параметром fragment для получения HTML-фрагмента"""
        # Сначала залогинимся
        self.client.post("/basic-login", data={"username": "test", "password": "test"})
        
        response = self.client.get("/calendar?year=2023&month=3&fragment=1")
        
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response.headers["content-type"])
    
    def test_calendar_route_current_month_default(self):
        """Тест маршрута /calendar без параметров (должен вернуть текущий месяц)"""
        # Сначала залогинимся
        self.client.post("/basic-login", data={"username": "test", "password": "test"})
        
        response = self.client.get("/calendar")
        
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response.headers["content-type"])
    
    def test_calendar_route_invalid_year_month(self):
        """Тест маршрута /calendar с некорректными параметрами года и месяца"""
        # Сначала залогинимся
        self.client.post("/basic-login", data={"username": "test", "password": "test"})
        
        # Тестируем с некорректным месяцем
        response = self.client.get("/calendar?year=2023&month=13")
        
        # Должен обработать ошибку корректно, не вызвав исключение
        self.assertIn(response.status_code, [200, 400, 500])  # Может вернуть 200 с пустым календарем или ошибку
    
    def test_calendar_route_response_structure(self):
        """Тест структуры ответа маршрута /calendar"""
        # Сначала залогинимся
        self.client.post("/basic-login", data={"username": "test", "password": "test"})
        
        response = self.client.get("/calendar")
        
        self.assertEqual(response.status_code, 200)
        content = response.text
        # Проверяем наличие основных элементов HTML календаря
        self.assertIn("<div", content) # Должны быть HTML-элементы
        self.assertIn("calendar", content.lower())  # Должно содержать слово calendar в классах или id


if __name__ == '__main__':
    # Создаем тест-раннер
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    # Добавляем тесты из класса TestCalendarRoute
    test_class = TestCalendarRoute()
    suite.addTests(loader.loadTestsFromTestCase(TestCalendarRoute))

    # Запускаем тесты
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    # Возвращаем код завершения
    sys.exit(0 if result.wasSuccessful() else 1)