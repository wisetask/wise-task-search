-- Инициализация схемы семантического поиска WiseTask в PostgreSQL (pgvector).
-- Выполняется под суперпользователем (например, через docker-entrypoint-initdb.d
-- или вручную: psql "$SEARCH_DATABASE_URL" -f init.sql).
--
-- Схемы таблиц сохранены такими же, как в SQLite-версии: изменился только тип
-- колонки embedding (BLOB -> vector(1024)).

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    category TEXT,
    embedding vector(1024) NOT NULL
);

CREATE TABLE IF NOT EXISTS plugins (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    category TEXT,
    graph_type TEXT,
    plugin_type TEXT,
    embedding vector(1024) NOT NULL
);

-- HNSW-индексы под косинусное расстояние (оператор <=>), требуется pgvector >= 0.5.0.
CREATE INDEX IF NOT EXISTS tasks_embedding_hnsw_idx
    ON tasks USING hnsw (embedding vector_cosine_ops);

CREATE INDEX IF NOT EXISTS plugins_embedding_hnsw_idx
    ON plugins USING hnsw (embedding vector_cosine_ops);
