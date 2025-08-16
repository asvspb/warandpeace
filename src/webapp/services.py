
import sqlite3
from typing import List, Dict, Any, Optional
from src.database import get_db_connection, get_content_hash_groups, list_articles_by_content_hash, list_dlq_items

def get_articles(page: int = 1, page_size: int = 50, q: Optional[str] = None, 
                 start_date: Optional[str] = None, end_date: Optional[str] = None, has_content: int = 1) -> (List[Dict[str, Any]], int):
    """Fetches a paginated list of articles with optional filters."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        base_query = "FROM articles WHERE 1=1"
        count_query = "SELECT COUNT(*) " + base_query
        select_query = "SELECT id, title, url, canonical_link, published_at " + base_query
        
        params = {}
        
        if q:
            select_query += " AND title LIKE :q"
            count_query += " AND title LIKE :q"
            params['q'] = f"%{q}%"
            
        if start_date:
            select_query += " AND published_at >= :start_date"
            count_query += " AND published_at >= :start_date"
            params['start_date'] = start_date

        if end_date:
            select_query += " AND published_at <= :end_date"
            count_query += " AND published_at <= :end_date"
            params['end_date'] = end_date

        if has_content == 1:
            select_query += " AND content IS NOT NULL AND content <> ''"
            count_query += " AND content IS NOT NULL AND content <> ''"

        # Get total count for pagination
        total_articles = cursor.execute(count_query, params).fetchone()[0]
        
        # Get paginated articles
        select_query += " ORDER BY published_at DESC LIMIT :limit OFFSET :offset"
        params['limit'] = page_size
        params['offset'] = (page - 1) * page_size
        
        articles = cursor.execute(select_query, params).fetchall()
        
        return [dict(row) for row in articles], total_articles

def get_article_by_id(article_id: int) -> Optional[Dict[str, Any]]:
    """Fetches a single article by its ID."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM articles WHERE id = ?", (article_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

def get_dashboard_stats() -> Dict[str, Any]:
    """Fetches statistics for the main dashboard."""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

            stats: Dict[str, Any] = {}

            # Total articles
            cursor.execute("SELECT COUNT(*) FROM articles")
            stats['total_articles'] = cursor.fetchone()[0]

            # Last published article date
            cursor.execute("SELECT MAX(published_at) FROM articles")
            last_published = cursor.fetchone()[0]
            stats['last_published_date'] = last_published if last_published else "N/A"

            # DLQ count
            cursor.execute("SELECT COUNT(*) FROM dlq")
            stats['dlq_count'] = cursor.fetchone()[0]

            return stats
    except sqlite3.Error:
        # Graceful fallback when tables/database are not available
        return {'total_articles': 0, 'last_published_date': 'N/A', 'dlq_count': 0}

# --- Duplicates Services ---

def get_duplicate_groups() -> List[Dict[str, Any]]:
    """Reuses the database function to get duplicate groups."""
    return get_content_hash_groups(min_count=2)

def get_articles_by_hash(content_hash: str) -> List[Dict[str, Any]]:
    """Reuses the database function to get articles by a specific hash."""
    return list_articles_by_content_hash(content_hash)

# --- DLQ Services ---

def get_dlq_items(entity_type: Optional[str] = None) -> List[Dict[str, Any]]:
    """Reuses the database function to get DLQ items."""
    return list_dlq_items(entity_type=entity_type, limit=500)
