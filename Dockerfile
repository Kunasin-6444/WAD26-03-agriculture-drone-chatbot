FROM python:3.12.10-slim@sha256:fd95fa221297a88e1cf49c55ec1828edd7c5a428187e67b5d1805692d11588db AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    ANONYMIZED_TELEMETRY=False
WORKDIR /app
COPY requirements.txt constraints.txt ./
RUN pip install --no-cache-dir -r requirements.txt && pip check

FROM base AS test
COPY app ./app
COPY scripts ./scripts
COPY tests ./tests
COPY data ./data
RUN python -B -m pytest -q tests -p no:cacheprovider

FROM base AS runtime
RUN groupadd --gid 10001 chatbot && useradd --uid 10001 --gid chatbot --create-home chatbot \
    && mkdir -p /app/chroma_db /app/cache && chown -R chatbot:chatbot /app
COPY --chown=chatbot:chatbot app ./app
COPY --chown=chatbot:chatbot scripts ./scripts
COPY --chown=chatbot:chatbot data ./data
COPY --chown=chatbot:chatbot tests/data ./tests/data
USER chatbot
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/ready', timeout=3).close()"
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
