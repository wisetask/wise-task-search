# WiseTask Semantic Search API

Сервис семантического поиска по задачам и плагинам для WiseTask.

API принимает сущности (tasks/plugins), строит для них эмбеддинги с помощью модели `BAAI/bge-m3` из `sentence-transformers`, сохраняет данные в PostgreSQL с расширением [pgvector](https://github.com/pgvector/pgvector) и выполняет поиск по смыслу средствами самой СУБД (косинусное расстояние `<=>`, HNSW-индекс).

## Возможности

- Индексация задач: загрузка списка задач и сохранение эмбеддингов в PostgreSQL (pgvector).
- Индексация плагинов: загрузка списка плагинов и сохранение эмбеддингов в PostgreSQL (pgvector).
- Семантический поиск: поиск наиболее похожих задач/плагинов по текстовому запросу (векторный поиск на стороне БД).
- Docker-запуск: быстрый старт без установки окружения локально.

## Настройка базы данных (pgvector)

Сервис требует PostgreSQL с установленным расширением `vector` (рекомендуется образ `pgvector/pgvector:pg17`) и pgvector >= 0.5.0 для HNSW-индексов.

Схемы таблиц `tasks` и `plugins` сохранены такими же, как в SQLite-версии, изменился только тип колонки `embedding`: `BLOB` -> `vector(1024)`. Схему можно создать заранее с помощью [`init.sql`](./init.sql) (выполняется под суперпользователем), либо автоматически при старте сервиса (`TaskStorage.init_db`).

Параметры подключения берутся из переменных окружения (см. [`.env.example`](./.env.example)):

| Переменная | По умолчанию | Описание |
| --- | --- | --- |
| `SEARCH_DATABASE_URL` | — | Полная строка подключения (имеет приоритет над остальными) |
| `SEARCH_DB_HOST` | `DB_HOST` / `DB` / `localhost` | Хост PostgreSQL |
| `SEARCH_DB_PORT` | `DB_PORT` / `5432` | Порт PostgreSQL |
| `SEARCH_DB` | `wise_task_search` | Имя базы данных |
| `SEARCH_DB_USER` | `wise_task_search` | Пользователь БД |
| `SEARCH_DB_PASSWORD` | `wise_task_search` | Пароль БД |
| `EMBEDDING_DIM` | `1024` | Размерность эмбеддингов (`BAAI/bge-m3` -> 1024) |

### Локальный запуск БД

```bash
docker compose up -d wise-task-search-db
```

Затем запустите сервис с `SEARCH_DB_PORT=5432` (или `SEARCH_DATABASE_URL`), указывающим на этот контейнер.

## Запуск (Docker)

Собрать образ и запустить контейнер:

```bash
cd wise-task-search
docker buildx build --platform linux/amd64 -t wise-task-search .
docker run -d --name wise-task-search --gpus all -p 8001:8001 semantic-search-api
```

После старта API будет доступен по адресу:

- http://localhost:8001

Примечание: при первом запуске модель может загружаться/инициализироваться некоторое время — это нормально.

## Проверка работы

### Health check

```bash
curl http://localhost:8001/health
```

Ожидаемый ответ:

```json
{"status":"ok"}
```

## Быстрые примеры

### Индексация задач (bulk)

```bash
curl -X POST http://localhost:8001/tasks/bulk \
  -H "Content-Type: application/json" \
  -d '{
    "tasks": [
      { "id": "1", "name": "Задача про графы", "description": "описание", "category": "Graphs" }
    ]
  }'
```

### Поиск задач

```bash
curl -X POST http://localhost:8001/tasks/search \
  -H "Content-Type: application/json" \
  -d '{ "query": "поиск про графы", "top_k": 3 }'
```

### Индексация плагинов (bulk)

```bash
curl -X POST http://localhost:8001/plugins/bulk \
  -H "Content-Type: application/json" \
  -d '{
    "plugins": [
      {
        "id": "p1",
        "name": "Graph Builder",
        "description": "строит граф",
        "category": "Graphs",
        "graphType": "DAG",
        "pluginType": "builder"
      }
    ]
  }'
```

### Поиск плагинов

```bash
curl -X POST http://localhost:8001/plugins/search \
  -H "Content-Type: application/json" \
  -d '{ "query": "построение графа", "top_k": 3 }'
```
