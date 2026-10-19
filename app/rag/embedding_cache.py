"""Content-addressed cache for ingestion embeddings; query budgets stay unchanged."""
import hashlib
import json
import logging
import math
from pathlib import Path
from uuid import uuid4

logger = logging.getLogger(__name__)
DIMENSIONS = 3072


def _valid(values) -> bool:
    return (isinstance(values, list) and len(values) == DIMENSIONS and any(values)
            and all(type(v) in (int, float) and math.isfinite(v) for v in values))


def _identity(text: str, model: str) -> dict:
    return {"format": "raw_text_v1", "model": model, "dimensions": DIMENSIONS,
            "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()}


def _path(identity: dict, directory: Path) -> Path:
    return directory / f"{hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()}.json"


def _load(identity: dict, directory: Path):
    try:
        cached = json.loads(_path(identity, directory).read_text(encoding="utf-8"))
        if cached.get("identity") == identity and _valid(cached.get("vector")):
            return cached["vector"]
    except (OSError, ValueError, AttributeError):
        pass
    return None


def _store(identity: dict, vector, directory: Path) -> None:
    path = _path(identity, directory)
    temporary = path.with_name(f"{path.name}.{uuid4().hex}.tmp")
    try:
        directory.mkdir(parents=True, exist_ok=True)
        temporary.write_text(json.dumps({"identity": identity, "vector": vector}), encoding="utf-8")
        temporary.replace(path)
    except OSError as exc:
        logger.warning("Embedding cache write skipped (%s)", type(exc).__name__)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def cached_document_embedding(text: str, model: str, directory: Path, embedder) -> list[float]:
    identity = _identity(text, model)
    cached = _load(identity, directory)
    if cached is not None:
        return cached
    vector = embedder(text)
    if not _valid(vector):
        raise ValueError("Document embedding must contain 3072 finite, nonzero vector values")
    _store(identity, vector, directory)
    return vector


def cached_document_embeddings(texts: list[str], model: str, directory: Path, batch_embedder) -> list[list[float]]:
    """Vectors for ``texts`` in order; only distinct cache misses reach ``batch_embedder``.

    ``batch_embedder(list[str]) -> list[vector]`` must return one vector per text. Nothing is
    written to the cache unless every returned vector is valid, so a bad batch cannot poison it.
    """
    identities = [_identity(text, model) for text in texts]
    found: dict[str, list[float]] = {}
    missing: dict[str, str] = {}
    for text, identity in zip(texts, identities):
        digest = identity["sha256"]
        if digest in found or digest in missing:
            continue
        cached = _load(identity, directory)
        if cached is not None:
            found[digest] = cached
        else:
            missing[digest] = text
    if missing:
        vectors = batch_embedder(list(missing.values()))
        if len(vectors) != len(missing) or not all(_valid(vector) for vector in vectors):
            raise ValueError("Batch embedding must return one valid 3072-value vector per text")
        for (digest, text), vector in zip(missing.items(), vectors):
            _store(_identity(text, model), vector, directory)
            found[digest] = vector
    return [found[identity["sha256"]] for identity in identities]
