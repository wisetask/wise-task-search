import functools
import os
from pathlib import Path
from typing import List
import torch
import numpy as np
from sentence_transformers import SentenceTransformer

from .models import PluginIn, PluginWithScore, TaskIn, TaskWithScore
from .storage import TaskStorage

DEFAULT_MODEL_NAME = "BAAI/bge-m3"


def _resolve_model_path() -> str:
    local_override = os.getenv("BGE_M3_MODEL_PATH")
    if local_override:
        return str(Path(local_override).expanduser())

    custom_model = os.getenv("BGE_M3_MODEL")
    if custom_model:
        return custom_model

    return DEFAULT_MODEL_NAME


@functools.lru_cache(maxsize=1)
def _load_model() -> SentenceTransformer:
    model_id = _resolve_model_path()
    device = "cuda" if torch.cuda.is_available() else "cpu"
    return SentenceTransformer(model_id, device=device)


def warmup_model() -> SentenceTransformer:
    return _load_model()


def encode_text(text: str) -> np.ndarray:
    embedding = _load_model().encode(
        text, convert_to_numpy=True, normalize_embeddings=True
    )
    if embedding.ndim > 1:
        embedding = embedding[0]
    return embedding.astype(np.float32)


class SemanticTaskSearchService:
    def __init__(self, storage: TaskStorage):
        self.storage = storage

    def index_task(self, task: TaskIn) -> None:
        text = "\n".join(
            filter(None, [task.name, task.description or "", task.category or ""])
        )
        embedding = encode_text(text)
        self.storage.upsert_task(task, embedding)

    def bulk_index(self, tasks: List[TaskIn]) -> None:
        for task in tasks:
            self.index_task(task)

    def search(self, query: str, top_k: int = 3) -> List[TaskWithScore]:
        if not query or not query.strip():
            return []

        query_vec = encode_text(query)
        matches = self.storage.search_tasks(query_vec, top_k)

        return [
            TaskWithScore(
                id=match.id,
                name=match.name,
                description=match.description,
                category=match.category,
                score=match.score,
            )
            for match in matches
        ]


class SemanticPluginSearchService:
    def __init__(self, storage: TaskStorage):
        self.storage = storage

    def index_plugin(self, plugin: PluginIn) -> None:
        text = "\n".join(
            filter(
                None,
                [
                    plugin.name,
                    plugin.description or "",
                    plugin.category or "",
                    plugin.graphType or "",
                    plugin.pluginType or "",
                ],
            )
        )
        embedding = encode_text(text)
        self.storage.upsert_plugin(plugin, embedding)

    def bulk_index(self, plugins: List[PluginIn]) -> None:
        for plugin in plugins:
            self.index_plugin(plugin)

    def search(self, query: str, top_k: int = 3) -> List[PluginWithScore]:
        if not query or not query.strip():
            return []

        query_vec = encode_text(query)
        matches = self.storage.search_plugins(query_vec, top_k)

        return [
            PluginWithScore(
                id=match.id,
                name=match.name,
                description=match.description,
                category=match.category,
                graphType=match.graph_type,
                pluginType=match.plugin_type,
                score=match.score,
            )
            for match in matches
        ]
