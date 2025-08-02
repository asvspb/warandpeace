from requests_html import HTMLSession
import re
from datetime import datetime
from summarizer import summarize_text_local

def get_article_text(url: str) -> str | None:
    """
    Синхронно получает полный текст статьи по URL, используя точный селектор и кодировку.
    """
    session = HTMLSession()
    try:
        r = session.get(url, timeout=30)
        r.raise_for_status()
        r.html.encoding = 'windows-1251'
        
        article_elements = r.html.find('td.topic_text')
        
        article_body = None
        for element in article_elements:
            if not element.find('a.a_header_article', first=True):
                article_body = element
                break

        if article_body:
            clean_text = '\n'.join(line.strip() for line in article_body.text.split('\n') if line.strip())
            return clean_text
        else:
            print(f"Не удалось найти текст статьи для {url}")
            return None
            
    except Exception as e:
        print(f"Произошла ошибка при загрузке или парсинге статьи {url}: {e}")
        return None
    finally:
        session.close()

def get_articles_from_page(page=1):
    session = HTMLSession()
    if page == 1:
        list_url = "https://warandpeace.ru/ru/news/"
    else:
        list_url = f"https://warandpeace.ru/ru/news/_/_/page={page}/"
    
    try:
        response = session.get(list_url, timeout=20)
        response.raise_for_status()
        response.html.encoding = 'windows-1251'
        
        articles_data = []
        tables = response.html.find('table')

        for table in tables:
            title_tag = table.find('a.a_header_article', first=True)
            time_tag = table.find('td.topic_info_top', first=True)

            if title_tag and time_tag:
                title = title_tag.text.strip()
                link = list(title_tag.absolute_links)[0]

                time_text = time_tag.text.strip()
                time_match = re.search(r'(\d{2}\.\d{2}\.\d{2}) (\d{2}:\d{2})', time_text)
                if time_match:
                    date_str, time_str = time_match.groups()
                else:
                    date_str, time_str = '??.??.??', '??:??'

                if title and link:
                    if not any(d['link'] == link for d in articles_data):
                        articles_data.append({
                            'date': date_str,
                            'time': time_str,
                            'title': title,
                            'link': link
                        })
        return articles_data
    except Exception as e:
        print(f"Произошла ошибка при парсинге страницы новостей: {e}")
        return []
    finally:
        session.close()

def main():
    print("--- Запуск парсера ---")
    latest_articles = get_articles_from_page(1)
    
    if latest_articles:
        latest_articles.sort(key=lambda x: (
            datetime.strptime(x['date'], '%d.%m.%y'), 
            datetime.strptime(x['time'], '%H:%M')
        ), reverse=True)
        
        latest_article = latest_articles[0]
        
        print(f"\n--- Найдена последняя новость ---")
        print(f"Заголовок: {latest_article['title']}")
        print(f"Ссылка: {latest_article['link']}")
        
        print("\n--- Получение полного текста статьи... ---")
        full_text = get_article_text(latest_article['link'])
        
        if full_text:
            print("--- Полный текст статьи получен. ---")
            
            print("--- Суммаризация текста... ---")
            summary = summarize_text_local(full_text)
            if summary:
                print("\n--- РЕЗЮМЕ НОВОСТИ ---")
                print(summary)
            else:
                print("Не удалось получить резюме.")
        else:
            print("Не удалось получить полный текст статьи.")
    else:
        print("Не удалось найти последние новости.")

    print("\n--- Парсер завершил работу ---")

if __name__ == "__main__":
    main()