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
                contents=[
                    types.Content(
                        parts=[
                            types.Part.from_text(
                                text=text
                            )
                        ]
                    )
                ],
            )

            if not result.embeddings:
                raise RuntimeError(
                    "Gemini returned no embedding"
                )

            return result.embeddings[0].values

        except Exception as exc:
            last_exc = exc
            exc_str = str(exc)

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
