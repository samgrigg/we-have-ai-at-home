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
                conn.execute(files("household").joinpath("schema.sql").read_text())
                PostgresSaver(conn).setup()
            finally:
                conn.execute("SELECT pg_advisory_unlock(728346126)")


def main():
    from household.config import Settings

    Database(Settings().database_url).setup()
    print("Database initialized")


if __name__ == "__main__":
    main()
