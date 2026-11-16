# Multi-stage build: dependencies and the embedding model are prepared in the
# builder; the final image has only what the API needs and runs as non-root.

FROM python:3.12-slim AS builder
ENV PIP_NO_CACHE_DIR=1 HF_HOME=/opt/hf
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
COPY requirements.txt .
# CPU-only PyTorch keeps the image far smaller than the default GPU build.
RUN pip install torch --index-url https://download.pytorch.org/whl/cpu \
    && pip install -r requirements.txt
# Bake the model into the image so a cold start does not download it.
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')"

FROM python:3.12-slim
ENV PATH="/opt/venv/bin:$PATH" \
    HF_HOME=/opt/hf \
    HF_HUB_OFFLINE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    RESUMEFIT_DATABASE_URL=sqlite:////data/resumefit.db
RUN useradd --create-home --uid 10001 appuser \
    && mkdir /data && chown appuser:appuser /data
COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /opt/hf /opt/hf
WORKDIR /app
COPY app ./app
USER appuser
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
