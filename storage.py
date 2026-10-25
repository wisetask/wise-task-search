import logging
import os
import time
from dataclasses import dataclass
from typing import List, Optional

import numpy as np
import psycopg
from pgvector.psycopg import register_vector
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from .models import PluginIn, TaskIn

logger = logging.getLogger(__name__)

# Размерность эмбеддингов модели BAAI/bge-m3.
DEFAULT_EMBEDDING_DIM = 1024

# Ожидание готовности БД при старте (compose может поднимать сервис раньше Postgres).
DB_CONNECT_RETRIES = int(os.getenv("DB_CONNECT_RETRIES", "10"))
DB_CONNECT_RETRY_DELAY = float(os.getenv("DB_CONNECT_RETRY_DELAY", "2"))


def _env(names: List[str], default: str) -> str:
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    return default


def _resolve_conninfo() -> str:
    """Собирает строку подключения к PostgreSQL.

    Приоритет: явный DSN (SEARCH_DATABASE_URL/DATABASE_URL), иначе отдельные
    переменные окружения. Переменные названы в стиле остальных сервисов WiseTask
    (DB/DB_PORT), при этом у сервиса поиска есть собственные SEARCH_DB_*.
    """
    dsn = os.getenv("SEARCH_DATABASE_URL") or os.getenv("DATABASE_URL")
    if dsn:
        return dsn

    host = _env(["SEARCH_DB_HOST", "DB_HOST", "DB"], "localhost")
    port = _env(["SEARCH_DB_PORT", "DB_PORT"], "5432")
    dbname = _env(["SEARCH_DB", "SEARCH_DB_NAME"], "wise_task_search")
    user = _env(["SEARCH_DB_USER"], "wise_task_search")
    password = _env(["SEARCH_DB_PASSWORD"], "wise_task_search")
    return psycopg.conninfo.make_conninfo(
        host=host,
        port=port,
        dbname=dbname,
        user=user,
        password=password,
    )


def _configure_connection(conn: psycopg.Connection) -> None:
    register_vector(conn)


@dataclass
class TaskMatch:
    id: str
    name: str
    description: str
    category: str
    score: float


@dataclass
class PluginMatch:
    id: str
    name: str
    description: str
    category: str
    graph_type: str
    plugin_type: str
    score: float


class TaskStorage:
    """Хранилище задач и плагинов с эмбеддингами в PostgreSQL (pgvector)."""

    def __init__(
        self,
        conninfo: Optional[str] = None,
        embedding_dim: Optional[int] = None,
        pool_min_size: int = 1,
        pool_max_size: int = 10,
    ):
        self.conninfo = conninfo or _resolve_conninfo()
        self.embedding_dim = embedding_dim or int(
            os.getenv("EMBEDDING_DIM", DEFAULT_EMBEDDING_DIM)
        )
        self.pool_min_size = pool_min_size
        self.pool_max_size = pool_max_size
        self._pool: Optional[ConnectionPool] = None

    def _connect(self) -> psycopg.Connection:
        """Открывает соединение с PostgreSQL, повторяя попытки при старте."""
        last_exc: Optional[psycopg.Error] = None
        for attempt in range(1, DB_CONNECT_RETRIES + 1):
            try:
                return psycopg.connect(self.conninfo, autocommit=True)
            except psycopg.OperationalError as exc:
                last_exc = exc
                logger.warning(
                    "Не удалось подключиться к PostgreSQL (попытка %s/%s): %s",
                    attempt,
                    DB_CONNECT_RETRIES,
                    exc,
                )
                if attempt < DB_CONNECT_RETRIES:
                    time.sleep(DB_CONNECT_RETRY_DELAY)
        assert last_exc is not None
        raise last_exc

    def init_db(self) -> None:
        """Создаёт расширение pgvector, таблицы и индексы, затем открывает пул."""
        with self._connect() as conn:
            try:
                conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
            except psycopg.Error as exc:  # например, нет прав суперпользователя
                logger.warning(
                    "Не удалось создать расширение vector (%s). Убедитесь, что оно "
                    "установлено и создано заранее, например через init.sql.",
                    exc,
                )

        with self._connect() as conn:
            register_vector(conn)
            conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT,
                    category TEXT,
                    embedding vector({self.embedding_dim}) NOT NULL
                )
                """
            )
            conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS plugins (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT,
                    category TEXT,
                    graph_type TEXT,
                    plugin_type TEXT,
                    embedding vector({self.embedding_dim}) NOT NULL
                )
                """
            )
            self._create_vector_index(conn, "tasks")
            self._create_vector_index(conn, "plugins")

        if self._pool is None:
            self._pool = ConnectionPool(
                self.conninfo,
                min_size=self.pool_min_size,
                max_size=self.pool_max_size,
                configure=_configure_connection,
                kwargs={"autocommit": True},
                open=False,
            )
            self._pool.open()

    @staticmethod
    def _create_vector_index(conn: psycopg.Connection, table: str) -> None:
        index_name = f"{table}_embedding_hnsw_idx"
        try:
            conn.execute(
                f"""
                CREATE INDEX IF NOT EXISTS {index_name}
                ON {table} USING hnsw (embedding vector_cosine_ops)
                """
            )
        except psycopg.Error as exc:
            # HNSW доступен с pgvector >= 0.5.0. Поиск продолжит работать
            # (точным перебором), просто без ускорения.
            logger.warning("Не удалось создать HNSW-индекс для %s: %s", table, exc)

    def _get_pool(self) -> ConnectionPool:
        if self._pool is None:
            self.init_db()
        assert self._pool is not None
        return self._pool

    def close(self) -> None:
        if self._pool is not None:
            self._pool.close()
            self._pool = None

    def upsert_task(self, task: TaskIn, embedding: np.ndarray) -> None:
        vector = np.asarray(embedding, dtype=np.float32)
        with self._get_pool().connection() as conn:
            conn.execute(
                """
                INSERT INTO tasks (id, name, description, category, embedding)
                VALUES (%(id)s, %(name)s, %(description)s, %(category)s, %(embedding)s)
                ON CONFLICT (id) DO UPDATE SET
                    name = EXCLUDED.name,
                    description = EXCLUDED.description,
                    category = EXCLUDED.category,
                    embedding = EXCLUDED.embedding
                """,
                {
                    "id": task.id,
                    "name": task.name,
                    "description": task.description or "",
                    "category": task.category or "",
                    "embedding": vector,
                },
            )

    def upsert_plugin(self, plugin: PluginIn, embedding: np.ndarray) -> None:
        vector = np.asarray(embedding, dtype=np.float32)
        with self._get_pool().connection() as conn:
            conn.execute(
                """
                INSERT INTO plugins (
                    id, name, description, category, graph_type, plugin_type, embedding
                )
                VALUES (
                    %(id)s, %(name)s, %(description)s, %(category)s,
                    %(graph_type)s, %(plugin_type)s, %(embedding)s
                )
                ON CONFLICT (id) DO UPDATE SET
                    name = EXCLUDED.name,
                    description = EXCLUDED.description,
                    category = EXCLUDED.category,
                    graph_type = EXCLUDED.graph_type,
                    plugin_type = EXCLUDED.plugin_type,
                    embedding = EXCLUDED.embedding
                """,
                {
                    "id": plugin.id,
                    "name": plugin.name,
                    "description": plugin.description or "",
                    "category": plugin.category or "",
                    "graph_type": plugin.graphType or "",
                    "plugin_type": plugin.pluginType or "",
                    "embedding": vector,
                },
            )

    def delete_task(self, task_id: str) -> bool:
        with self._get_pool().connection() as conn:
            cursor = conn.execute("DELETE FROM tasks WHERE id = %s", (task_id,))
            return cursor.rowcount > 0

    def delete_plugin(self, plugin_id: str) -> bool:
        with self._get_pool().connection() as conn:
            cursor = conn.execute("DELETE FROM plugins WHERE id = %s", (plugin_id,))
            return cursor.rowcount > 0

    def search_tasks(
        self, embedding: np.ndarray, top_k: int = 3
    ) -> List[TaskMatch]:
        top_k = max(int(top_k), 0)
        if top_k == 0:
            return []
        vector = np.asarray(embedding, dtype=np.float32)
        with self._get_pool().connection() as conn:
            with conn.cursor(row_factory=dict_row) as cursor:
                rows = cursor.execute(
                    """
                    SELECT
                        id,
                        name,
                        description,
                        category,
                        1 - (embedding <=> %(embedding)s) AS score
                    FROM tasks
                    ORDER BY embedding <=> %(embedding)s
                    LIMIT %(top_k)s
                    """,
                    {"embedding": vector, "top_k": top_k},
                ).fetchall()

        return [
            TaskMatch(
                id=row["id"],
                name=row["name"],
                description=row["description"] or "",
                category=row["category"] or "",
                score=float(row["score"]),
            )
            for row in rows
        ]

    def search_plugins(
        self, embedding: np.ndarray, top_k: int = 3
    ) -> List[PluginMatch]:
        top_k = max(int(top_k), 0)
        if top_k == 0:
            return []
        vector = np.asarray(embedding, dtype=np.float32)
        with self._get_pool().connection() as conn:
            with conn.cursor(row_factory=dict_row) as cursor:
                rows = cursor.execute(
                    """
                    SELECT
                        id,
                        name,
                        description,
                        category,
                        graph_type,
                        plugin_type,
                        1 - (embedding <=> %(embedding)s) AS score
                    FROM plugins
                    ORDER BY embedding <=> %(embedding)s
                    LIMIT %(top_k)s
                    """,
                    {"embedding": vector, "top_k": top_k},
                ).fetchall()

        return [
            PluginMatch(
                id=row["id"],
                name=row["name"],
                description=row["description"] or "",
                category=row["category"] or "",
                graph_type=row["graph_type"] or "",
                plugin_type=row["plugin_type"] or "",
                score=float(row["score"]),
            )
            for row in rows
        ]

