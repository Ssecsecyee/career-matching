"""Delete expired conversation/cache records only; preserves job/training data."""
import argparse
from src.config import load_local_settings
from src.repositories.mysql_connection import connect_mysql


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    load_local_settings()
    connection = connect_mysql()
    tables = ("response_cache", "recommendation_evidence", "model_invocations", "chat_messages", "chat_sessions")
    try:
        connection.begin()
        with connection.cursor() as cur:
            for table in tables:
                cur.execute("SELECT COUNT(*) AS n FROM " + table + " WHERE expires_at<=UTC_TIMESTAMP(6)")
                print(table, "expired:", cur.fetchone()["n"])
                if args.apply:
                    cur.execute("DELETE FROM " + table + " WHERE expires_at<=UTC_TIMESTAMP(6) LIMIT 1000")
        if args.apply:
            connection.commit()
        else:
            connection.rollback()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


if __name__ == "__main__":
    main()
