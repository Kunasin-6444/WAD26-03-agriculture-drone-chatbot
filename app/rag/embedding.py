from __future__ import annotations

import os
import time

from dotenv import load_dotenv
from google import genai
from google.genai import types


load_dotenv()


# --------------------------------------------------
# Gemini client
# --------------------------------------------------

api_key = os.getenv("GOOGLE_API_KEY")

if not api_key:
    raise RuntimeError(
        "GOOGLE_API_KEY is not set"
    )

client = genai.Client(
    api_key=api_key
)


# --------------------------------------------------
# Embedding configuration
# --------------------------------------------------

EMBEDDING_MODEL = "gemini-embedding-2"


# --------------------------------------------------
# Create embedding
# --------------------------------------------------

def embed_text(
    text: str,
    max_retries: int = 5,
    timeout_seconds: float = 30.0,
) -> list[float]:
    """
    Create one embedding vector for one text.

    Retry temporary Gemini server or rate limit failures with exponential backoff.
    """

    if not text.strip():
        raise ValueError(
            "Cannot embed empty text"
        )

    return _embed_parts([types.Part.from_text(text=text)], max_retries, timeout_seconds)


def embed_pdf_page(
    pdf_bytes: bytes,
    max_retries: int = 5,
    timeout_seconds: float = 30.0,
) -> list[float]:
    """Embed the actual PDF bytes, including visual content, without transcription."""
    if not pdf_bytes.startswith(b"%PDF-"):
        raise ValueError("Expected PDF bytes")
    return _embed_parts(
        [types.Part.from_bytes(data=pdf_bytes, mime_type="application/pdf")],
        max_retries, timeout_seconds,
    )


class EmbeddingShapeError(RuntimeError):
    """The service answered, but not with one nonempty vector per input."""


def _embed_parts(parts: list[types.Part], max_retries: int, timeout_seconds: float) -> list[float]:
    return _embed_request([types.Content(parts=parts)], max_retries, timeout_seconds)[0]


def embed_texts(
    texts: list[str],
    batch_size: int | None = None,
    max_retries: int = 5,
    timeout_seconds: float = 60.0,
) -> list[list[float]]:
    """Embed many document texts with one API call per batch.

    A response that does not hold exactly one vector per input is never trusted
    (vectors cannot be matched back to texts); that batch is embedded one by one.
    """
    if any(not text.strip() for text in texts):
        raise ValueError("Cannot embed empty text")
    size = batch_size or int(os.getenv("EMBED_BATCH_SIZE", "24"))
    if size < 1:
        raise ValueError("Embedding batch size must be positive")
    vectors: list[list[float]] = []
    for start in range(0, len(texts), size):
        batch = texts[start:start + size]
        try:
            vectors.extend(_embed_request(
                [types.Content(parts=[types.Part.from_text(text=text)]) for text in batch],
                max_retries, timeout_seconds))
        except EmbeddingShapeError:
            vectors.extend(embed_text(text, max_retries, timeout_seconds) for text in batch)
    return vectors


def _embed_request(contents: list[types.Content], max_retries: int, timeout_seconds: float) -> list[list[float]]:

    if max_retries < 1 or timeout_seconds <= 0:
        raise ValueError("Retry count and timeout must be positive")

    last_exc: Exception | None = None

    for attempt in range(max_retries):
        try:
            result = client.models.embed_content(
                model=EMBEDDING_MODEL,
                config=types.EmbedContentConfig(http_options=types.HttpOptions(
                    timeout=int(timeout_seconds * 1000),
                    retry_options=types.HttpRetryOptions(attempts=1),
                )),
                contents=contents,
            )

            embeddings = result.embeddings or []
            if len(embeddings) != len(contents) or not all(item.values for item in embeddings):
                if len(contents) == 1:
                    raise RuntimeError("Gemini must return exactly one nonempty embedding")
                raise EmbeddingShapeError(
                    f"Expected {len(contents)} nonempty embeddings, got {len(embeddings)}")

            return [item.values for item in embeddings]

        except EmbeddingShapeError:
            raise
        except Exception as exc:
            last_exc = exc
            exc_str = str(exc)

            # Invalid inputs/auth/model errors will not recover through backoff.
            if getattr(exc, "code", None) in {400, 401, 403, 404}:
                break

            if attempt == max_retries - 1:
                break

            # If 429 RESOURCE_EXHAUSTED, wait longer (60s) for rate-limit window to reset
            if "429" in exc_str or "RESOURCE_EXHAUSTED" in exc_str:
                delay = 60 * (attempt + 1)
            else:
                delay = 5 * (2 ** attempt)

            print(
                f"Embedding request rate-limited/failed ({last_exc!r}). "
                f"Retrying in {delay}s "
                f"(attempt {attempt + 1}/{max_retries})...",
                flush=True,
            )

            time.sleep(delay)

    raise RuntimeError(
        f"Embedding request failed after {max_retries} attempts"
    ) from last_exc
