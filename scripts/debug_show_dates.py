
import sqlite3
import os

DATABASE_PATH = os.path.join(os.path.dirname(__file__), '..', 'database', 'articles.db')

def check_dates_in_db():
    print(f"Проверяю даты в файле: {DATABASE_PATH}")
    if not os.path.exists(DATABASE_PATH):
        print("Файл базы данных не найден.")
        return

    try:
        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()
        
        # Запрос для получения всех уникальных ДАТ (без времени) из колонки published_at
        cursor.execute("SELECT DISTINCT date(published_at) FROM articles ORDER BY date(published_at) DESC")
        dates = cursor.fetchall()
        conn.close()

        if not dates:
            print("В таблице `articles` нет записей с датами.")
            return

        print("Найдены следующие уникальные даты публикаций:")
        for d in dates:
            print(f"- {d[0]}")

    except Exception as e:
        print(f"Произошла ошибка при работе с базой данных: {e}")

if __name__ == "__main__":
    check_dates_in_db()
