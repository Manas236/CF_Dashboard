"""MySQL access. The app only ever touches the dedicated database from .env."""
import pymysql
import pymysql.cursors

from . import config


def get_connection():
    """New connection to the dedicated analytics database (DictCursor)."""
    cfg = config.MYSQL
    return pymysql.connect(
        host=cfg["host"],
        port=cfg["port"],
        user=cfg["user"],
        password=cfg["password"],
        database=cfg["database"],
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=False,
    )


def ensure_schema():
    """Create the database (if we have the privilege) and all tables.

    Idempotent: every statement in schema.sql is CREATE ... IF NOT EXISTS.
    """
    cfg = config.MYSQL
    try:
        conn = pymysql.connect(
            host=cfg["host"], port=cfg["port"],
            user=cfg["user"], password=cfg["password"], charset="utf8mb4",
        )
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "CREATE DATABASE IF NOT EXISTS `%s` CHARACTER SET utf8mb4 "
                    "COLLATE utf8mb4_unicode_ci" % cfg["database"]
                )
            conn.commit()
    except pymysql.MySQLError:
        # No CREATE privilege — fine as long as the database already exists
        # (the connect below will fail loudly if it doesn't).
        pass

    sql = (config.PROJECT_ROOT / "schema.sql").read_text(encoding="utf-8")
    conn = get_connection()
    with conn:
        with conn.cursor() as cur:
            for statement in sql.split(";"):
                if statement.strip():
                    cur.execute(statement)
            _ensure_indexes(cur)
        conn.commit()


# Secondary indexes that may be missing on databases created before they were
# added to schema.sql (CREATE TABLE IF NOT EXISTS never alters existing tables).
SECONDARY_INDEXES = [
    ("hourly_path_stats", "idx_path_site_path", "(site, path, hour_start)"),
    ("hourly_error_path_stats", "idx_errpath_site_path", "(site, path, hour_start)"),
]


def _ensure_indexes(cur):
    for table, index, columns in SECONDARY_INDEXES:
        cur.execute(
            "SELECT COUNT(*) FROM information_schema.statistics "
            "WHERE table_schema = DATABASE() AND table_name = %s AND index_name = %s",
            (table, index),
        )
        if cur.fetchone()["COUNT(*)"] == 0:
            cur.execute(f"ALTER TABLE {table} ADD INDEX {index} {columns}")


def fetch_all(sql, params=None):
    """Run a read query on a fresh connection, return list of dicts."""
    conn = get_connection()
    with conn:
        with conn.cursor() as cur:
            cur.execute(sql, params or ())
            return cur.fetchall()


def fetch_one(sql, params=None):
    conn = get_connection()
    with conn:
        with conn.cursor() as cur:
            cur.execute(sql, params or ())
            return cur.fetchone()
