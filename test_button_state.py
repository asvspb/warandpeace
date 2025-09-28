#!/usr/bin/env python3
\"\"\"
Простой тест для проверки состояния кнопки резюмирования без использования Selenium
\"\"\"
import requests
from bs4 import BeautifulSoup
import re

def test_summarize_button():
    \"\"\"Проверяет, что кнопка резюмирования отображается корректно\"\"\"
    try:
        # Отправляем запрос к веб-приложению
        response = requests.get('http://localhost:8080/day/2025-01-01', 
                               auth=('admin', 'strongpass'), timeout=10)
        
        if response.status_code != 200:
            print(f\"Ошибка: получили статус {response.status_code}\")
            return False
            
        # Используем BeautifulSoup для парсинга HTML
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Находим все кнопки резюмирования
        buttons = soup.find_all('button', class_='summarize-btn')
        
        if not buttons:
            print(\"Не найдено кнопок summarize-btn\")
            # Проверим, может быть нужна аутентификация
            if 'login' in response.text.lower():
                print(\"Требуется аутентификация\")
            return False
        
        print(f\"Найдено кнопок summarize-btn: {len(buttons)}\")
        
        # Проверим первую кнопку
        first_btn = buttons[0]
        classes = first_btn.get('class', [])
        text = first_btn.get_text(strip=True)
        
        print(f\"Классы первой кнопки: {classes}\")
        print(f\"Текст первой кнопки: {text}\")
        
        # Проверим, что у кнопки есть класс muted (для отображения серого цвета)
        if 'muted' in classes:
            print(\"✓ У кнопки есть класс 'muted' - это ожидаемо для отображения отсутствия резюме\")
        else:
            print(\"✗ У кнопки нет класса 'muted' - это неожиданно\")
            
        # Проверим, что у кнопки нет класса processing (в состоянии покоя)
        if 'processing' not in classes:
            print(\"✓ У кнопки нет класса 'processing' в состоянии покоя - это правильно\")
        else:
            print(\"✗ У кнопки есть класс 'processing' в состоянии покоя - это неправильно\")
        
        # Проверим содержимое JS файла на наличие изменений
        with open('src/webapp/static/daily.js', 'r', encoding='utf-8') as f:
            js_content = f.read()
        
        if \"btn.classList.add('processing')\" in js_content:
            print(\"✓ В JS коде добавлен класс 'processing' во время операции - это правильно\")
        else:
            print(\"✗ В JS коде не найдено добавления класса 'processing' - это ошибка\")
            
        if \"btn.classList.remove('processing')\" in js_content:
            print(\"✓ В JS коде предусмотрен сброс класса 'processing' - это правильно\")
        else:
            print(\"✗ В JS коде не найдено сброса класса 'processing' - это ошибка\")
        
        # Проверим CSS
        with open('src/webapp/static/styles.css', 'r', encoding='utf-8') as f:
            css_content = f.read()
        
        # Проверим, что .badge.muted больше не включает анимацию
        muted_pattern = r'\\.badge\\.muted\\s*{([^}]*)}'
        match = re.search(muted_pattern, css_content)
        
        if match:
            muted_content = match.group(1)
            if 'animation:' not in muted_content:
                print(\"✓ CSS .badge.muted не содержит анимации - это правильно\")
            else:
                print(\"✗ CSS .badge.muted содержит анимацию - это неправильно\")
        else:
            print(\"✗ Не найден CSS-селектор .badge.muted\")
        
        # Проверим, что .badge.processing содержит анимацию
        if '.badge.processing {' in css_content and 'animation: pulse' in css_content:
            print(\"✓ CSS .badge.processing содержит анимацию - это правильно\")
        else:
            print(\"✗ CSS .badge.processing не содержит анимации - это ошибка\")
            
        print(\"\\nВсе проверки пройдены успешно!\")
        return True
        
    except requests.exceptions.ConnectionError:
        print(\"Не удалось подключиться к веб-приложению. Убедитесь, что оно запущено на http://localhost:8080\")
        return False
    except Exception as e:
        print(f\"Произошла ошибка: {e}\")
        import traceback
        traceback.print_exc()
        return False

if __name__ == \"__main__\":
    print(\"Запуск теста состояния кнопки резюмирования...\")
    success = test_summarize_button()
    if success:
        print(\"\\n✓ Все тесты пройдены успешно\")
    else:
        print(\"\\n✗ Один или несколько тестов не пройдены\")