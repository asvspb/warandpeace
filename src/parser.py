import requests
from bs4 import BeautifulSoup
import re
from datetime import datetime

def get_article_text(url: str) -> str | None:
    """
    Получает полный текст статьи по URL.
    """
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.36'
    }
    try:
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        response.encoding = 'windows-1251'
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Ищем основной контейнер с текстом новости
        article_body = soup.find('div', class_='news_text')
        
        if article_body:
            # Собираем все текстовые блоки, игнорируя лишнее
            text_parts = [p.text for p in article_body.find_all('p')]
            return "\n".join(text_parts).strip()
        else:
            return None
            
    except requests.exceptions.RequestException as e:
        print(f"Ошибка при загрузке текста статьи {url}: {e}")
        return None
    except Exception as e:
        print(f"Произошла ошибка при парсинге текста статьи {url}: {e}")
        return None

def get_articles_from_page(page=1):
    """
    Парсит страницу новостей и возвращает последние статьи с заголовком, ссылкой и временем.
    """
    if page == 1:
        list_url = "https://warandpeace.ru/ru/news/"
    else:
        list_url = f"https://warandpeace.ru/ru/news/_/_/page={page}/"
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.36'
    }
    try:
        response = requests.get(list_url, headers=headers)
        response.raise_for_status()
        response.encoding = 'windows-1251'
        soup = BeautifulSoup(response.text, 'html.parser')
        articles_data = []

        for table in soup.find_all('table'):
            title_tag = table.find('a', class_='a_header_article')
            time_tag = table.find('td', class_='topic_info_top')

            if title_tag and time_tag:
                title = title_tag.text.strip()
                link = title_tag['href']
                if not link.startswith('http'):
                    link = f"https://warandpeace.ru{link}"

                time_text = time_tag.text.strip()
                time_match = re.search(r'(\d{2}\.\d{2}\.\d{2}) (\d{2}:\d{2})', time_text)
                if time_match:
                    date_str = time_match.group(1)
                    time_str = time_match.group(2)
                else:
                    date_str = '??.??.??'
                    time_str = '??:??'

                if title and link:
                    # To avoid duplicates from the same page
                    if not any(d['link'] == link for d in articles_data):
                        articles_data.append({
                            'date': date_str,
                            'time': time_str,
                            'title': title,
                            'link': link
                        })
        return articles_data
    except requests.exceptions.RequestException as e:
        if e.response and e.response.status_code == 404:
            return [] # Page not found, stop pagination
        print(f"Ошибка при загрузке страницы новостей: {e}")
        return []
    except Exception as e:
        print(f"Произошла ошибка при парсинге страницы новостей: {e}")
        return []

if __name__ == "__main__":
    all_articles = []
    page = 1
    
    # Collect articles from pages until we have at least two days of news
    # or we run out of pages.
    dates_found = set()
    while True:
        articles_on_page = get_articles_from_page(page)
        if not articles_on_page:
            break
        
        all_articles.extend(articles_on_page)
        
        for article in articles_on_page:
            dates_found.add(article['date'])
        
        if len(dates_found) > 2:
            break
            
        page += 1

    # Remove duplicates
    unique_articles = []
    seen_links = set()
    for article in all_articles:
        if article['link'] not in seen_links:
            unique_articles.append(article)
            seen_links.add(article['link'])
            
    # Get the latest two dates
    all_dates = sorted(list(set(a['date'] for a in unique_articles)), 
                       key=lambda d: datetime.strptime(d, '%d.%m.%y'), 
                       reverse=True)
    
    dates_to_print = all_dates[:2]
    
    # Group articles by date
    articles_by_date = {}
    for date_str in dates_to_print:
        articles_by_date[date_str] = []

    for article in unique_articles:
        if article['date'] in articles_by_date:
            articles_by_date[article['date']].append(article)

    # Print articles
    for date_str in dates_to_print:
        print(date_str)
        # sort articles by time
        sorted_articles = sorted(articles_by_date[date_str], key=lambda x: x['time'], reverse=True)
        for article in sorted_articles:
            print(f"{article.get('time', '??:??')}  \t{article['title']}")
        print()

    print("Парсер завершил работу.")