"""임베딩(문장을 숫자 벡터로). 운영은 Gemini, 테스트는 키 없이 쓸 수 있는 해시 임베딩을 쓴다."""
import hashlib
import math
import re
import time
from typing import Protocol

from app.config import settings


class Embedder(Protocol):
    dim: int

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


def _normalize(v: list[float]) -> list[float]:
    """단위 벡터로 만든다(차원을 줄여 쓰는 Gemini 임베딩은 정규화되어 있지 않다)."""
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


class GeminiEmbedder:
    """Gemini 임베딩. 무료 티어의 분당 한도에 걸리면 안내된 시간만큼 기다렸다가 다시 시도한다."""

    def __init__(self, api_key: str, model: str, dim: int, batch_size: int = 20):
        from google import genai
        self._client = genai.Client(api_key=api_key)
        self._model, self.dim, self._batch = model, dim, batch_size
        self.calls = 0

    def _embed(self, texts: list[str], task: str) -> list[list[float]]:
        from google.genai import errors, types
        cfg = types.EmbedContentConfig(task_type=task, output_dimensionality=self.dim)
        for attempt in range(8):
            try:
                self.calls += 1
                res = self._client.models.embed_content(model=self._model, contents=texts, config=cfg)
                return [_normalize(list(e.values)) for e in res.embeddings]
            except errors.APIError as e:
                if getattr(e, "code", None) not in (429, 500, 502, 503, 504) or attempt == 7:
                    raise
                wait = 10.0
                m = re.search(r"retry in ([\d.]+)s", str(e)) or re.search(r"'retryDelay': '(\d+)s'", str(e))
                if m:
                    wait = float(m.group(1)) + 1
                time.sleep(min(max(wait, 5.0 * (attempt + 1)), 90.0))
        raise RuntimeError("임베딩 재시도 한도 초과")

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(texts), self._batch):
            out += self._embed(texts[i:i + self._batch], "RETRIEVAL_DOCUMENT")
        return out

    def embed_query(self, text: str) -> list[float]:
        return self._embed([text], "RETRIEVAL_QUERY")[0]


class HashEmbedder:
    """테스트용 가짜 임베딩: 글자 2-gram을 해시로 벡터에 더한다. 같은 글자가 많이 겹칠수록 가깝다(의미는 이해하지 못한다)."""

    def __init__(self, dim: int = 768):
        self.dim = dim

    def _vec(self, text: str) -> list[float]:
        v = [0.0] * self.dim
        t = re.sub(r"\s+", "", text.lower())
        for i in range(len(t) - 1):
            h = int(hashlib.md5(t[i:i + 2].encode("utf-8")).hexdigest(), 16)
            v[h % self.dim] += 1.0
        return _normalize(v)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vec(text)


_override: Embedder | None = None
_gemini: GeminiEmbedder | None = None


def set_embedder(e: Embedder | None) -> None:
    """테스트에서 가짜 임베딩을 끼워 넣는 용도."""
    global _override
    _override = e


def get_embedder() -> Embedder | None:
    global _gemini
    if _override is not None:
        return _override
    if not settings.gemini_api_key:
        return None
    if _gemini is None:
        _gemini = GeminiEmbedder(settings.gemini_api_key, settings.gemini_embedding_model, settings.embedding_dim)
    return _gemini
