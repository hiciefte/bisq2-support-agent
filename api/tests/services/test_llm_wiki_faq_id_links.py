"""Tests for _faq_id_links connection lifecycle in llm_wiki_update_service.

Review finding: ``with sqlite3.connect(...)`` only commits/rolls back the
transaction - it never closes the connection, so every call leaked a handle.
The helper must close its connection on every path (rows found, missing
table, sqlite errors).
"""

import sqlite3
from types import SimpleNamespace

import pytest
from app.services.faq.slug_manager import SlugManager
from app.services.knowledge_updates import llm_wiki_update_service as svc


class _TrackingConnection:
    """Proxy recording close() calls while forwarding everything else."""

    def __init__(self, conn, closed):
        object.__setattr__(self, "_conn", conn)
        object.__setattr__(self, "_closed", closed)

    def close(self):
        self._closed.append(True)
        self._conn.close()

    def __getattr__(self, name):
        return getattr(self._conn, name)

    def __setattr__(self, name, value):
        setattr(self._conn, name, value)


@pytest.fixture
def faq_db(tmp_path):
    db_path = tmp_path / "faqs.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE faqs (id INTEGER PRIMARY KEY, question TEXT)")
    conn.execute("INSERT INTO faqs (id, question) VALUES (1, 'How do I trade?')")
    conn.commit()
    conn.close()
    return db_path


@pytest.fixture
def track_connections(monkeypatch):
    closed = []
    real_connect = sqlite3.connect

    def tracking_connect(*args, **kwargs):
        return _TrackingConnection(real_connect(*args, **kwargs), closed)

    monkeypatch.setattr(svc.sqlite3, "connect", tracking_connect)
    return closed


def _settings(db_path):
    return SimpleNamespace(FAQ_DB_PATH=str(db_path))


class TestFaqIdLinksConnectionLifecycle:
    def test_connection_closed_after_successful_lookup(self, faq_db, track_connections):
        links = svc._faq_id_links(_settings(faq_db), ["1", "999"], SlugManager())

        assert "1" in links
        assert links["1"].startswith("/faq/")
        assert track_connections == [True]

    def test_connection_closed_when_faqs_table_missing(
        self, tmp_path, track_connections
    ):
        db_path = tmp_path / "faqs.db"
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE unrelated (id INTEGER)")
        conn.commit()
        conn.close()
        track_connections.clear()  # ignore the setup connection

        links = svc._faq_id_links(_settings(db_path), ["1"], SlugManager())

        assert links == {}
        assert track_connections == [True]
