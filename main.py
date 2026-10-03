import sys
from pathlib import Path
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware 

PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from semantic_search_api.models import (
    BulkIndexRequest,
    PluginBulkIndexRequest,
    PluginSearchRequest,
    SearchRequest,
    TaskWithScore,
    PluginWithScore,
)
from semantic_search_api.semantic import (
    SemanticPluginSearchService,
    SemanticTaskSearchService,
    warmup_model,
)
from semantic_search_api.storage import TaskStorage

app = FastAPI(title="WiseTask Semantic Search API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://wisetask.ru",
        "https://wisetask.ru:82",
        "https://wisetask.ru:82/graphql",
        "http://localhost:5173",
        "http://localhost:3000",
        "http://localhost:3150"
        "http://localhost:8080",
        "http://127.0.0.1:8080",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

storage = TaskStorage()
storage.init_db()
semantic_service = SemanticTaskSearchService(storage)
plugin_semantic_service = SemanticPluginSearchService(storage)


@app.on_event("startup")
def preload_model() -> None:
    warmup_model()


@app.on_event("shutdown")
def close_storage() -> None:
    storage.close()


@app.get("/health")
def health_check() -> dict:
    return {"status": "ok"}


@app.post("/tasks/bulk")
def bulk_index(request: BulkIndexRequest) -> dict:
    semantic_service.bulk_index(request.tasks)
    return {"indexed": len(request.tasks)}


@app.post("/tasks/search", response_model=list[TaskWithScore])
def search_tasks(request: SearchRequest):
    return semantic_service.search(request.query, request.top_k)


@app.post("/plugins/bulk")
def bulk_index_plugins(request: PluginBulkIndexRequest) -> dict:
    plugin_semantic_service.bulk_index(request.plugins)
    return {"indexed": len(request.plugins)}


@app.post("/plugins/search", response_model=list[PluginWithScore])
def search_plugins(request: PluginSearchRequest):
    return plugin_semantic_service.search(request.query, request.top_k)


if __name__ == "__main__":
    uvicorn.run("semantic_search_api.main:app", host="0.0.0.0", port=8001)
