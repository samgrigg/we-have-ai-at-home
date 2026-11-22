from importlib.resources import files

import psycopg
from psycopg.rows import dict_row


class Database:
    def __init__(self, url: str):
        self.url = url

    def connect(self, *, autocommit=False):
        return psycopg.connect(
            self.url, row_factory=dict_row, autocommit=autocommit, connect_timeout=10
        )

    def setup(self):
        from langgraph.checkpoint.postgres import PostgresSaver

        with self.connect(autocommit=True) as conn:
            # Serialize schema initialization across API/worker release jobs.
            conn.execute("SELECT pg_advisory_lock(728346126)")
            try:
                with conn.transaction():
                    conn.execute(files("household").joinpath("schema.sql").read_text())
                    conn.execute(
                        "CREATE TABLE IF NOT EXISTS app_migrations "
                        "(version TEXT PRIMARY KEY, applied_at TIMESTAMPTZ DEFAULT now())"
                    )
                    for migration in sorted(
                        files("household").joinpath("migrations").iterdir(), key=lambda p: p.name
                    ):
                        if not migration.name.endswith(".sql"):
                            continue
                        applied = conn.execute(
                            "SELECT 1 FROM app_migrations WHERE version=%s", (migration.name,)
                        ).fetchone()
                        if not applied:
                            conn.execute(migration.read_text())
                            conn.execute(
                                "INSERT INTO app_migrations(version) VALUES (%s)", (migration.name,)
                            )
                PostgresSaver(conn).setup()
            finally:
                conn.execute("SELECT pg_advisory_unlock(728346126)")


def main():
    from household.config import Settings

    Database(Settings().database_url).setup()
    print("Database initialized")


if __name__ == "__main__":
    main()
