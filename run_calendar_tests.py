#!/usr/bin/env python3
"""
Скрипт для запуска тестов календаря без использования pytest
"""
import unittest
import sys
import os

# Добавляем путь к src в sys.path для импорта модулей
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

# Импортируем тестируемую функцию
from webapp.services import get_month_calendar_data

# Определяем тесты для функции get_month_calendar_data
class TestGetMonthCalendarData(unittest.TestCase):
    """Тесты для функции get_month_calendar_data в services.py"""

    def test_get_month_calendar_data_current_month(self):
        """Тест получения данных календаря для текущего месяца"""
        from datetime import date
        today = date.today()
        year = today.year
        month = today.month

        result = get_month_calendar_data(year, month)

        # Проверяем основные ключи в результате
        self.assertIn('year', result)
        self.assertIn('month', result)
        self.assertIn('weeks', result)
        self.assertIn('prev', result)
        self.assertIn('next', result)
        
        # Проверяем значения года и месяца
        self.assertEqual(result['year'], year)
        self.assertEqual(result['month'], month)
        
        # Проверяем структуру weeks
        self.assertIsInstance(result['weeks'], list)
        self.assertGreater(len(result['weeks']), 0)
        
        # Проверяем структуру недель и дней
        for week in result['weeks']:
            self.assertIn('days', week)
            self.assertIn('total', week)
            self.assertIn('summarized', week)
            self.assertIn('all_summarized', week)
            
            for day in week['days']:
                self.assertIn('date', day)
                self.assertIn('day', day)
                self.assertIn('in_month', day)
                self.assertIn('total', day)
                self.assertIn('summarized', day)

    def test_get_month_calendar_data_specific_month(self):
        """Тест получения данных календаря для конкретного месяца"""
        year = 2023
        month = 3  # Март

        result = get_month_calendar_data(year, month)

        self.assertEqual(result['year'], year)
        self.assertEqual(result['month'], month)
        self.assertIsInstance(result['weeks'], list)
        
        # Проверяем, что в марте 2023 есть 5 недель
        self.assertEqual(len(result['weeks']), 5)

    def test_get_month_calendar_data_prev_next_months(self):
        """Тест получения данных о предыдущем и следующем месяцах"""
        # Тестируем март 2023
        result = get_month_calendar_data(2023, 3)

        self.assertEqual(result['prev'], {'year': 2023, 'month': 2})  # Февраль
        self.assertEqual(result['next'], {'year': 2023, 'month': 4})  # Апрель

    def test_get_month_calendar_data_year_boundary(self):
        """Тест перехода через границу года"""
        # Тестируем декабрь
        result = get_month_calendar_data(2023, 12)

        self.assertEqual(result['prev'], {'year': 2023, 'month': 11})  # Ноябрь
        self.assertEqual(result['next'], {'year': 2024, 'month': 1})   # Январь следующего года

        # Тестируем январь
        result = get_month_calendar_data(2023, 1)

        self.assertEqual(result['prev'], {'year': 2022, 'month': 12})  # Декабрь предыдущего года
        self.assertEqual(result['next'], {'year': 2023, 'month': 2})   # Февраль

    def test_get_month_calendar_data_with_data(self):
        """Тест получения данных календаря с реальными данными из БД"""
        from datetime import date
        # Тестируем с текущим месяцем
        today = date.today()
        result = get_month_calendar_data(today.year, today.month)
        
        # Проверяем, что структура правильная
        self.assertIn('year', result)
        self.assertIn('month', result)
        self.assertIn('weeks', result)
        
        # Проверяем, что дни имеют правильные свойства
        for week in result['weeks']:
            for day in week['days']:
                self.assertIsInstance(day['date'], str)
                self.assertIsInstance(day['day'], int)
                self.assertIsInstance(day['in_month'], bool)
                self.assertIsInstance(day['total'], int)
                self.assertIsInstance(day['summarized'], int)
                
                # Проверяем формат даты
                self.assertEqual(len(day['date']), 10) # YYYY-MM-DD
                self.assertGreaterEqual(day['total'], 0)
                self.assertGreaterEqual(day['summarized'], 0)
                self.assertLessEqual(day['summarized'], day['total'])

    def test_get_month_calendar_data_all_summarized_flag(self):
        """Тест флага all_summarized в неделях"""
        from datetime import date
        today = date.today()
        result = get_month_calendar_data(today.year, today.month)
        
        # Проверяем, что флаг all_summarized присутствует имеет правильный тип
        for week in result['weeks']:
            self.assertIn('all_summarized', week)
            self.assertIsInstance(week['all_summarized'], bool)
            
            # Проверяем логику флага: all_summarized = (total > 0 && total == summarized)
            if week['total'] > 0:
                expected = week['total'] == week['summarized']
                self.assertEqual(week['all_summarized'], expected)
            else:
                # Если total = 0, то all_summarized должен быть False
                self.assertFalse(week['all_summarized'])


if __name__ == '__main__':
    # Создаем тест-раннер
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    # Добавляем тесты из класса TestGetMonthCalendarData
    test_class = TestGetMonthCalendarData()
    suite.addTests(loader.loadTestsFromTestCase(TestGetMonthCalendarData))

    # Запускаем тесты
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    # Возвращаем код завершения
    sys.exit(0 if result.wasSuccessful() else 1)