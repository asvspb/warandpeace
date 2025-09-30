#!/usr/bin/env python3
"""
Простой тест для проверки логики анимации кнопки резюмирования
"""
import unittest
import os
import sys

# Добавляем путь к исходникам
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

class TestAnimationLogic(unittest.TestCase):
    def test_css_changes(self):
        """Проверка, что CSS изменения корректны"""
        with open('src/webapp/static/styles.css', 'r', encoding='utf-8') as f:
            css_content = f.read()
            
        # Проверяем, что класс muted больше не включает анимацию
        self.assertIn('.badge.muted {', css_content)
        self.assertIn('color: var(--muted);', css_content)
        self.assertNotIn('animation: pulse 1s infinite alternate;', css_content.split('.badge.muted {')[-1].split('}')[0])
        
        # Проверяем, что класс processing добавлен и включает анимацию
        self.assertIn('.badge.processing {', css_content)
        self.assertIn('animation: pulse 1s infinite alternate;', css_content)
        
        # Проверяем, что определение анимации pulse присутствует
        self.assertIn('@keyframes pulse {', css_content)
        
    def test_js_changes(self):
        """Проверка, что JavaScript изменения корректны"""
        with open('src/webapp/static/daily.js', 'r', encoding='utf-8') as f:
            js_content = f.read()
            
        # Проверяем, что код добавляет класс 'processing' вместо 'muted' при запуске
        self.assertIn("btn.classList.add('processing');", js_content)
        
        # Проверяем, что код удаляет класс 'processing' при ошибке
        self.assertIn("btn.classList.remove('processing');", js_content)
        
        # Проверяем, что мы больше не добавляем класс 'muted' при запуске процесса
        lines = js_content.split('\n')
        for line in lines:
            if 'classList.add' in line and 'muted' in line:
                # Должна быть только строка с исходным классом из HTML
                self.assertTrue('summarize-btn' in line or 'muted' in line.split('classList.add')[0])

if __name__ == '__main__':
    print("Тестирование логики анимации кнопки резюмирования...")
    unittest.main(verbosity=2)
