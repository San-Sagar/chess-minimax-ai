# Production image: runs the game server on port 7860 (any Docker host).
#   docker build -t chess-minimax-ai .
#   docker run -p 7860:7860 chess-minimax-ai        -> http://localhost:7860
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOST=0.0.0.0 \
    PORT=7860 \
    CHESS_MAX_AI_SECONDS=5 \
    CHESS_MAX_SEARCHES=2

RUN useradd --create-home --uid 1000 app
WORKDIR /app
COPY pyproject.toml README.md ./
COPY chess_ai ./chess_ai
COPY web ./web
RUN pip install --no-cache-dir -e .

USER app
EXPOSE 7860
CMD ["python", "-m", "chess_ai.server"]
