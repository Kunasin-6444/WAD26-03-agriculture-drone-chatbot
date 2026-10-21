# Hugging Face Spaces (Docker SDK). Built from the folder made by `python -m scripts.build_hf_space`.
# Spaces run the container as user id 1000 and route traffic to app_port 7860 (see README.md).
# The Space is public (LINE must reach /webhook) so the index is NOT in this image: scripts/fetch_index.py
# downloads it from a private dataset (HF_INDEX_REPO, HF_TOKEN) at start. The LINE inbox in /app/cache is
# lost on restart, which is acceptable for a test deployment.
# Secrets (LINE, KKU, Google, Tavily keys, HF_TOKEN) come from the Space settings as environment variables.
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
COPY --chown=user:user data ./data
COPY --chown=user:user scripts ./scripts
RUN mkdir -p /app/chroma_db /app/cache && chown -R user:user /app

USER user
EXPOSE 7860
CMD ["sh", "-c", "python -m scripts.fetch_index && exec python -m uvicorn app.main:app --host 0.0.0.0 --port 7860 --workers 1"]
