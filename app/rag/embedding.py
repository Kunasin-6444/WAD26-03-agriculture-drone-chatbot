from __future__ import annotations

import os
import time

from dotenv import load_dotenv
from google import genai
from google.genai import types
from google.genai.errors import ServerError


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
    max_retries: int = 3,
) -> list[float]:
    """
    Create one embedding vector for one text.

    Retry temporary Gemini server failures:

        5s -> 10s -> 20s
    """

    if not text.strip():
        raise ValueError(
            "Cannot embed empty text"
        )

    last_exc: Exception | None = None

    for attempt in range(max_retries):

        try:

            result = client.models.embed_content(
                model=EMBEDDING_MODEL,
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

        except ServerError as exc:

            last_exc = exc

            error_code = getattr(
                exc,
                "code",
                None,
            )

            # Retry temporary server errors only.
            if error_code not in {
                500,
                502,
                503,
                504,
            }:
                raise

        except Exception as exc:

            last_exc = exc

        if attempt == max_retries - 1:
            break

        delay = 5 * (2 ** attempt)

        print(
            f"Embedding request failed ({last_exc!r}). "
            f"Retrying in {delay}s "
            f"(attempt {attempt + 1}/{max_retries})..."
        )

        time.sleep(delay)

    raise RuntimeError(
        f"Embedding request failed after "
        f"{max_retries} attempts"
    ) from last_exc