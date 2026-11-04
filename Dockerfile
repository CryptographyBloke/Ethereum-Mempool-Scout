# --- build the dashboard ---------------------------------------------------
FROM node:22-alpine AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# --- python runtime (collector + API) ---------------------------------------
FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY mempool_scout ./mempool_scout
RUN pip install --no-cache-dir .
COPY --from=web /web/dist ./frontend/dist
ENV SCOUT_DB=/data/scout.sqlite
EXPOSE 8000
ENTRYPOINT ["python", "-m", "mempool_scout.process_manager"]
CMD ["all"]
