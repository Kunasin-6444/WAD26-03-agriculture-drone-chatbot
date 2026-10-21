# Render free web service (Docker), built by Render from the repo root as set in render.yaml.
# Only what the service runs on is copied: no PDFs, tests or docs (.dockerignore keeps .env out of the
# context). The index (document text) is not in git: scripts/fetch_index.py downloads it from the
# private Hugging Face dataset HF_INDEX_REPO with HF_TOKEN at start. The filesystem is ephemeral, so the
# LINE inbox in /app/cache is lost on every restart, redeploy or spin-down.
FROM python:3.12.10-slim@sha256:fd95fa221297a88e1cf49c55ec1828edd7c5a428187e67b5d1805692d11588db

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    ANONYMIZED_TELEMETRY=False \
    PDF_RETRIEVAL_MODE=text \
    HOME=/home/user

RUN useradd --create-home --uid 1000 user
WORKDIR /app

COPY requirements.txt constraints.txt ./
RUN pip install --no-cache-dir -r requirements.txt && pip check

COPY --chown=user:user app ./app
COPY --chown=user:user data/rich_menu_answers ./data/rich_menu_answers
COPY --chown=user:user scripts/fetch_index.py ./scripts/fetch_index.py
RUN mkdir -p /app/chroma_db /app/cache && chown -R user:user /app

USER user
EXPOSE 10000
# Render sets PORT (10000 by default).
CMD ["sh", "-c", "python -m scripts.fetch_index && exec python -m uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-10000} --workers 1"]
