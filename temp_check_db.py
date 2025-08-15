import sqlite3

DATABASE_NAME = "/home/asv-spb/Dev/my-coding/warandpeace/database/articles.db"

conn = sqlite3.connect(DATABASE_NAME)
cursor = conn.cursor()

cursor.execute("SELECT created_at, updated_at, published_at FROM articles ORDER BY id DESC LIMIT 5")
rows = cursor.fetchall()

for row in rows:
    print(row)

conn.close()