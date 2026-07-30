FROM python:3.11-slim

WORKDIR /app

# System deps:
#   git       - required by GitPython for cloning target repos
#   ripgrep   - used by the legacy code_search fallback
#   docker.io - CLI for talking to the mounted Docker socket (sandbox mode)
RUN apt-get update && apt-get install -y --no-install-recommends \
        git \
        ripgrep \
        docker.io \
    && rm -rf /var/lib/apt/lists/*

# Copy Python project metadata first so pip install is cached until deps change.
# README.md is required because pyproject references it via `readme = "README.md"`.
COPY pyproject.toml README.md ./

# Copy source packages before install so setuptools' package-find can locate them.
COPY app ./app
COPY agent ./agent
COPY llm ./llm
COPY tools ./tools
COPY demo ./demo

# Non-editable install - no dev extras in the production image.
RUN pip install --no-cache-dir .

# Directory where the agent clones target repos at runtime.
RUN mkdir -p /app/workspaces

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=2)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
