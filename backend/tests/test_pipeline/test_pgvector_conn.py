from lakehouse.db.pgvector_conn import get_pgvector_connection_string


class TestGetPgvectorConnectionString:
    def test_formats_connection_string(self):
        url = get_pgvector_connection_string(
            host="localhost",
            port=5433,
            db="mananeras",
            user="mananeras",
            password="secret",
        )
        assert url == "postgresql://mananeras:secret@localhost:5433/mananeras"
