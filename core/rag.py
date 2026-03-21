from __future__ import annotations

import hashlib
import importlib
import os
import threading
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple


@dataclass(slots=True)
class _StoredDoc:
    doc_id: str
    code: str
    metadata: Dict[str, Any]


class CodeRAG:
    def __init__(self, enabled: bool = False) -> None:
        self.enabled = bool(enabled)
        self._lock = threading.Lock()
        self._documents: Dict[str, _StoredDoc] = {}

        self._chroma_collection = None
        self._embedder = None

        if not self.enabled:
            return

        model_name = os.environ.get("RAG_EMBED_MODEL", "all-MiniLM-L6-v2").strip() or "all-MiniLM-L6-v2"
        persist_dir = os.environ.get(
            "RAG_PERSIST_DIR",
            os.path.join(os.getcwd(), "cache", "rag_chroma"),
        ).strip()

        try:
            chromadb = importlib.import_module("chromadb")
            sentence_transformers = importlib.import_module("sentence_transformers")

            SentenceTransformer = getattr(sentence_transformers, "SentenceTransformer", None)
            if SentenceTransformer is None:
                raise RuntimeError("SentenceTransformer not available")

            self._embedder = SentenceTransformer(model_name)

            client = chromadb.PersistentClient(path=persist_dir)
            self._chroma_collection = client.get_or_create_collection("code_chunks")

        except Exception:
            # graceful fallback
            self._embedder = None
            self._chroma_collection = None


    @staticmethod
    def _stable_id(code: str, metadata: Dict[str, Any]) -> str:
        meta_str = "|".join(f"{k}:{v}" for k, v in sorted((metadata or {}).items()))
        return hashlib.sha256(f"{code}|{meta_str}".encode("utf-8")).hexdigest()


    def add_document(self, code: str, metadata: Optional[Dict[str, Any]] = None) -> None:
        if not self.enabled:
            return

        text = str(code or "").strip()
        if not text:
            return

        meta = dict(metadata or {})
        doc_id = self._stable_id(text, meta)

        with self._lock:
            if doc_id in self._documents:
                return  # prevent duplicates
            self._documents[doc_id] = _StoredDoc(doc_id=doc_id, code=text, metadata=meta)

        if not (self._chroma_collection and self._embedder):
            return

        try:
            embedding = self._embedder.encode(text).tolist()

            self._chroma_collection.upsert(
                ids=[doc_id],
                documents=[text],
                metadatas=[meta],
                embeddings=[embedding],
            )
        except Exception:
            # fail silently → fallback still works
            pass


    def search(self, query: str, k: int = 5) -> List[Dict[str, Any]]:
        if not self.enabled:
            return []

        query_text = str(query or "").strip()
        if not query_text:
            return []

        top_k = max(1, int(k))

        # ---------------- VECTOR SEARCH ----------------
        if self._chroma_collection is not None and self._embedder is not None:
            try:
                query_embedding = self._embedder.encode(query_text).tolist()

                result = self._chroma_collection.query(
                    query_embeddings=[query_embedding],
                    n_results=top_k,
                )

                docs = (result.get("documents") or [[]])[0]
                metas = (result.get("metadatas") or [[]])[0]

                return [
                    {
                        "code": str(doc or ""),
                        "metadata": metas[i] if i < len(metas) and isinstance(metas[i], dict) else {},
                    }
                    for i, doc in enumerate(docs)
                ]

            except Exception:
                pass  # fallback to local search

        # ---------------- FALLBACK SEARCH ----------------
        query_tokens = set(query_text.lower().split())
        scored: List[Tuple[float, _StoredDoc]] = []

        with self._lock:
            docs = list(self._documents.values())

        for item in docs:
            code_tokens = set(item.code.lower().split())
            if not code_tokens:
                continue

            # Jaccard similarity
            intersection = len(query_tokens & code_tokens)
            union = len(query_tokens | code_tokens)

            if union == 0:
                continue

            score = intersection / union

            # boost if substring match (important improvement)
            if query_text.lower() in item.code.lower():
                score += 0.2

            if score > 0:
                scored.append((score, item))

        scored.sort(key=lambda x: x[0], reverse=True)

        return [
            {"code": item.code, "metadata": item.metadata}
            for _, item in scored[:top_k]
        ]


_GLOBAL_RAG: Optional[CodeRAG] = None
_GLOBAL_RAG_LOCK = threading.Lock()


def get_global_rag(enabled: bool = False) -> Optional[CodeRAG]:
    if not enabled:
        return None

    global _GLOBAL_RAG

    with _GLOBAL_RAG_LOCK:
        if _GLOBAL_RAG is None:
            _GLOBAL_RAG = CodeRAG(enabled=True)
        return _GLOBAL_RAG