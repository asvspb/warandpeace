#!/usr/bin/env python3
"""
Тест для проверки новых функций в браузере:
1. Анимация переключения фона на бейдже "Нет"
2. Отображение модального окна с прогрессом
3. Обработка успешного завершения и ошибок
"""

import time
import unittest
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options


class TestNewFeatures(unittest.TestCase):
    def setUp(self):
        """Настройка драйвера Chrome"""
        chrome_options = Options()
        # Раскомментируйте следующую строку для запуска в headless режиме
        # chrome_options.add_argument("--headless")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        
        # Укажите путь к Chrome драйверу, если он не в PATH
        # self.driver = webdriver.Chrome(executable_path="/path/to/chromedriver", options=chrome_options)
        self.driver = webdriver.Chrome(options=chrome_options)
        self.driver.implicitly_wait(10)

    def test_visual_feedback_animation(self):
        """Тест визуального фидбека при клике на 'Нет'"""
        driver = self.driver
        wait = WebDriverWait(driver, 20)
        
        # Открыть страницу с новостями за 22 августа 2025 года
        driver.get("http://admin:strongpass@localhost:8080/day/2025-09-28")
        
        # Найти кнопку "Нет" с классом summarize-btn
        no_button = wait.until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, "button.badge.muted.summarize-btn"))
        )
        
        # Проверить начальное состояние кнопки
        initial_class = no_button.get_attribute("class")
        print(f"Initial class: {initial_class}")
        
        # Кликнуть на кнопку
        no_button.click()
        
        # Проверить, что класс 'processing' добавлен для анимации
        time.sleep(1)  # Дать немного времени для визуального эффекта
        
        new_class = no_button.get_attribute("class")
        print(f"Class after click: {new_class}")
        
        # Проверить, что текст кнопки изменился на "Обработка..."
        wait.until(
            EC.text_to_be_present_in_element((By.CSS_SELECTOR, "button.summarize-btn"), "Обработка...")
        )
        
        # Проверить, что кнопка стала неактивной
        self.assertFalse(no_button.is_enabled())
        
        # Проверить, что добавлен класс 'processing' для анимации
        self.assertIn("processing", new_class)
        
        print("Все проверки анимации пройдены")
    
    def test_successful_summarization(self):
        """Тест успешной суммаризации (требует предварительной настройки или mock)"""
        # Этот тест требует особой настройки, т.к. суммаризация может занять время
        # и зависит от внешних LLM API
        driver = self.driver
        wait = WebDriverWait(driver, 30)  # Увеличенный таймаут для суммаризации
        
        driver.get("http://admin:strongpass@localhost:8080/day/2025-09-28")
        
        # Найти кнопку "Нет" с классом summarize-btn
        no_button = wait.until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, "button.badge.muted.summarize-btn"))
        )
        
        # Кликнуть на кнопку
        no_button.click()
        
        # Дождаться, что кнопка будет заменена на "Есть"
        # Это может занять время в зависимости от внешнего API
        success_badge = wait.until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "span.badge.success"))
        )
        
        # Проверить, что текст - "Есть"
        self.assertEqual(success_badge.text, "Есть")
        
        print("Тест успешной суммаризации пройден")
    
    def test_error_handling(self):
        """Тест обработки ошибок"""
        # Для тестирования ошибки можно использовать mock API или 
        # специально подготовленную статью, которая вызывает ошибку
        driver = self.driver
        wait = WebDriverWait(driver, 20)
        
        driver.get("http://localhost:8080/day/2025-08-22")
        
        # Найти кнопку "Нет" с классом summarize-btn
        no_button = wait.until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, "button.badge.muted.summarize-btn"))
        )
        
        # Сохранить ID элемента для будущей проверки
        initial_id = no_button.get_attribute("data-article-id")
        print(f"Testing error handling for article ID: {initial_id}")
        
        # Кликнуть на кнопку
        no_button.click()
        
        # В реальных условиях нужно проверить восстановление кнопки в случае ошибки
        print("Тест обработки ошибок выполнен")
    
    def tearDown(self):
        """Закрытие браузера"""
        self.driver.quit()


if __name__ == "__main__":
    print("Запуск тестов новых функций в браузере")
    print("Убедитесь, что приложение запущено на http://localhost:8080")
    print("Также убедитесь, что ChromeDriver установлен и доступен")
    
    # Для запуска: python test_new_features.py
    unittest.main(verbosity=2)