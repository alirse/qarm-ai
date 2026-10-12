FROM node:22-bookworm-slim AS coding
RUN npm install --global @openai/codex

FROM python:3.14.7-slim-bookworm
COPY --from=coding /usr/local/bin/node /usr/local/bin/node
COPY --from=coding /usr/local/lib/node_modules/@openai /usr/local/lib/node_modules/@openai
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*
RUN ln -s /usr/local/lib/node_modules/@openai/codex/bin/codex.js /usr/local/bin/codex \
    && pip install --no-cache-dir uv==0.12.23
WORKDIR /app
COPY . .
RUN SETUPTOOLS_SCM_PRETEND_VERSION=0.1.0 uv sync --locked --no-dev
ENV FCC_OPEN_BROWSER=false HOST=0.0.0.0 PORT=10000
EXPOSE 10000
CMD ["uv", "run", "--no-sync", "python", "scripts/qarm-cloud-start.py"]
