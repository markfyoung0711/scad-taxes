# Streamlit dashboard for Cloud Run.
#
# The warehouse is a single 3 MB DuckDB file that only changes when the
# pipeline is re-run, so it is baked into the image: no bucket to mount, no
# credentials at runtime, and the container is a complete, reproducible
# snapshot of what the site was serving.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

COPY --from=ghcr.io/astral-sh/uv:0.10.9 /uv /usr/local/bin/uv

WORKDIR /app

# Dependencies resolve from the lockfile and cache as their own layer, so a
# code change does not reinstall them.
COPY pyproject.toml uv.lock ./
COPY src/ ./src/
RUN uv sync --frozen --no-dev

COPY app/ ./app/
COPY sql/ ./sql/
COPY data/warehouse/scad.duckdb ./data/warehouse/scad.duckdb

ENV PATH="/app/.venv/bin:$PATH" \
    SCAD_ROOT=/app \
    STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false \
    STREAMLIT_SERVER_FILE_WATCHER_TYPE=none

EXPOSE 8080

# Cloud Run assigns the port; default to 8080 for a plain `docker run`.
#
# CORS and XSRF checks are off because the Cloudflare Worker rewrites the Host
# header to the run.app name while the browser still sends the custom domain as
# Origin. Streamlit compares the two and rejects the websocket with a 403,
# which renders as a blank page. Requests still have to carry the Worker's
# shared secret to get this far (see app/gate.py), and the app is read-only
# with no uploads or forms, so neither check is protecting anything here.
CMD exec streamlit run app/streamlit_app.py \
    --server.port "${PORT:-8080}" \
    --server.address 0.0.0.0 \
    --server.enableCORS false \
    --server.enableXsrfProtection false
