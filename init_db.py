"""One-shot schema setup: creates the database (if permitted) and all tables."""
import sys

import pymysql

from app import config, db

if __name__ == "__main__":
    try:
        db.ensure_schema()
    except pymysql.MySQLError as exc:
        sys.exit(f"MySQL setup failed: {exc}\n"
                 f"Check MYSQL_* in .env and that the database "
                 f"'{config.MYSQL['database']}' exists (see README step 3).")
    print(f"Schema ready in database '{config.MYSQL['database']}' "
          f"on {config.MYSQL['host']}:{config.MYSQL['port']}.")
