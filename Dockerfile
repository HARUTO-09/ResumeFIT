# Multi-stage build: dependencies and the embedding model are prepared in the
# builder; the final image has only what the API needs and runs as non-root.
# No PyTorch: the model runs through ONNX Runtime, so the API fits a 512 MB host.

FROM python:3.12-slim AS builder
ENV PIP_NO_CACHE_DIR=1 HF_HOME=/opt/hf HF_HUB_DISABLE_TELEMETRY=1
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
COPY requirements.txt .
RUN pip install -r requirements.txt
# Bake the pinned model files into the image so a cold start does not download them.
COPY app/core/embeddings.py /build/embeddings.py
RUN cd /build && python -c "from embeddings import OnnxEmbedder; OnnxEmbedder()"

FROM python:3.12-slim
ENV PATH="/opt/venv/bin:$PATH" \
    HF_HOME=/opt/hf \
    HF_HUB_OFFLINE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8000 \
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
    CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"PORT\"]}/health')"
# Hosts such as Render set PORT; locally it is 8000. One worker keeps memory low.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --workers 1"]
