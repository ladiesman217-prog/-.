"""Optional PostgreSQL persistence for Docker demonstration mode."""
import json
import os

def save_generation(data, topics, mode):
    dsn = os.environ.get("POSTGRES_DSN")
    if not dsn:
        return False
    import psycopg2
    with psycopg2.connect(dsn, connect_timeout=5) as connection:
        with connection.cursor() as cursor:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS generations (
                    id BIGSERIAL PRIMARY KEY,
                    major TEXT NOT NULL,
                    level TEXT NOT NULL,
                    language TEXT NOT NULL DEFAULT 'ru',
                    mode TEXT NOT NULL,
                    topics JSONB NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)
            cursor.execute(
                "INSERT INTO generations (major, level, language, mode, topics) VALUES (%s, %s, %s, %s, %s::jsonb)",
                (data["subject"], data["level"], data["language"], mode, json.dumps(topics, ensure_ascii=False)),
            )
    return True


def database_is_ready():
    dsn = os.environ.get("POSTGRES_DSN")
    if not dsn:
        return False
    import psycopg2
    with psycopg2.connect(dsn, connect_timeout=2) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            return cursor.fetchone()[0] == 1
