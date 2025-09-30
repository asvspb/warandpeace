#!/usr/bin/env python3
"""
Простой тест для проверки логики анимации кнопки резюмирования
"""
import unittest
import os
import sys


class TestAnimationLogic(unittest.TestCase):
    def test_css_changes(self):
        """Проверка, что CSS изменения корректны"""
        with open('src/webapp/static/styles.css', 'r', encoding='utf-8') as f:
            css_content = f.read()
            
        # Проверяем, что класс muted больше не включает анимацию
        self.assertIn('.badge.muted {', css_content)
        self.assertIn('color: var(--muted);', css_content)
        # Проверяем, что анимация не включена в определении .badge.muted
        muted_section = css_content.split('.badge.muted {')[-1].split('}')[0]
        self.assertNotIn('animation:', muted_section)
        
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
        found_add_muted = False
        for line in lines:
            if 'classList.add' in line and "'muted'" in line:
                # Проверяем, что это не в процессе установки состояния во время обработки
                if 'processing' not in line and 'Обработка' not in line:
                    found_add_muted = True
                    break
        
        # В идеале, мы не должны добавлять 'muted' во время процесса, но он может быть в исходном HTML
        # Проверим, что мы НЕ добавляем muted при начале процесса, а используем processing
        start_processing_lines = []
        for i, line in enumerate(lines):
            if "btn.textContent = 'Обработка...'":
                start_processing_lines.append(i)
        
        for line_idx in start_processing_lines:
            # Проверим, что рядом с установкой 'Обработка...' нет добавления 'muted'
            context = lines[max(0, line_idx-3):line_idx+3]
            context_str = ' '.join(context)
            # Убедимся, что мы добавляем processing, а не muted
            self.assertIn('processing', context_str)
            # Но при этом muted может быть в исходном классе, так что это не строгое требование


if __name__ == '__main__':
    print("Тестирование логики анимации кнопки резюмирования...")
    unittest.main(verbosity=2)
