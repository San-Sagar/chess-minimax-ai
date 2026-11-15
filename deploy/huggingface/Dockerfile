# Hugging Face Space: builds the game straight from the public GitHub repository.
# After pushing a new version to GitHub, use "Settings -> Factory rebuild" on the Space.
FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*
RUN useradd --create-home --uid 1000 user

ARG REPO=https://github.com/xyzhentai69-droid/chess-minimax-ai.git
WORKDIR /home/user
RUN git clone --depth 1 "$REPO" app
WORKDIR /home/user/app
RUN pip install --no-cache-dir -e .

ENV PYTHONUNBUFFERED=1 \
    HOST=0.0.0.0 \
    PORT=7860 \
    CHESS_MAX_AI_SECONDS=5 \
    CHESS_MAX_SEARCHES=2

USER user
EXPOSE 7860
CMD ["python", "-m", "chess_ai.server"]
