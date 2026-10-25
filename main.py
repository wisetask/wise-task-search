import sys
from pathlib import Path
import uvicorn
from fastapi import APIRouter, Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware

PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from semantic_search_api.auth import require_authenticated_user
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
        "http://localhost:5173",
        "http://localhost:3000",
        "http://localhost:3150",
        "http://localhost:8080",
        "http://127.0.0.1:8080",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

protected_router = APIRouter(dependencies=[Depends(require_authenticated_user)])

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


@protected_router.post("/tasks/bulk")
def bulk_index(request: BulkIndexRequest) -> dict:
    semantic_service.bulk_index(request.tasks)
    return {"indexed": len(request.tasks)}


@protected_router.post("/tasks/search", response_model=list[TaskWithScore])
def search_tasks(request: SearchRequest):
    return semantic_service.search(request.query, request.top_k)


@protected_router.delete("/tasks/{task_id}")
def delete_task(task_id: str) -> dict:
    if not storage.delete_task(task_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Задача {task_id} не найдена в индексе",
        )
    return {"deleted": True, "id": task_id}


@protected_router.post("/plugins/bulk")
def bulk_index_plugins(request: PluginBulkIndexRequest) -> dict:
    plugin_semantic_service.bulk_index(request.plugins)
    return {"indexed": len(request.plugins)}


@protected_router.post("/plugins/search", response_model=list[PluginWithScore])
def search_plugins(request: PluginSearchRequest):
    return plugin_semantic_service.search(request.query, request.top_k)


@protected_router.delete("/plugins/{plugin_id}")
def delete_plugin(plugin_id: str) -> dict:
    if not storage.delete_plugin(plugin_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Плагин {plugin_id} не найден в индексе",
        )
    return {"deleted": True, "id": plugin_id}


app.include_router(protected_router)


if __name__ == "__main__":
    uvicorn.run("semantic_search_api.main:app", host="0.0.0.0", port=8000)
