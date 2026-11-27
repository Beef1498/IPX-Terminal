FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    HOST=0.0.0.0 \
    PORT=8765 \
    IPX_DB_PATH=/data/ipx_terminal.db

WORKDIR /app

COPY pyproject.toml README.md CONTEXT.md QUANT_PLAYBOOK.md ./
COPY src ./src
COPY schemas ./schemas
COPY data/orchestration.json ./data/orchestration.json
COPY data/creator_watchlist.json ./data/creator_watchlist.json
COPY data/requirements_vcrm.json ./data/requirements_vcrm.json
COPY data/cultural_timeline.json ./data/cultural_timeline.json
COPY data/projects ./data/projects

RUN mkdir -p /data /app/exports/ipx-eval /app/data/quant_memos

EXPOSE 8765

CMD ["sh", "-c", "python3 -m ipx_terminal serve --host 0.0.0.0 --port ${PORT:-8765} --seed-if-empty"]
