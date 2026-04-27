from __future__ import annotations

import os
from pathlib import Path

import psycopg

BASE_DIR = Path(__file__).resolve().parent
SQL_FILE = BASE_DIR / "sql" / "001_init.sql"


def main() -> None:
    dsn = os.getenv("DATABASE_URL", "").strip()
    if not dsn:
        raise RuntimeError("DATABASE_URL is required")

    sql = SQL_FILE.read_text(encoding="utf-8")
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
        conn.commit()

    print("Database schema initialized.")


if __name__ == "__main__":
    main()
