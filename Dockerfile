FROM python:3.13-slim-bookworm

LABEL org.opencontainers.image.title="ICPC Author Agent"
LABEL org.opencontainers.image.description="Local LangGraph ICPC problem authoring agent with deterministic DOMjudge verification"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOME=/home/app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        g++ \
        default-jdk-headless \
        latexmk \
        lmodern \
        texlive-latex-base \
        texlive-latex-recommended \
        texlive-latex-extra \
        texlive-fonts-recommended \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN python -m pip install --no-cache-dir -r requirements.txt

COPY . .

RUN useradd --create-home --uid 1000 app \
    && mkdir -p /app/workspaces /app/.author-agent \
    && chown -R app:app /app

USER app

EXPOSE 8787

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8787/api/health', timeout=3)"]

CMD ["python", "-m", "author_studio", "--host", "0.0.0.0", "--port", "8787"]
