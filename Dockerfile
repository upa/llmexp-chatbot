# syntax=docker/dockerfile:1

# --- Base Stage ---
FROM python:3.12-slim AS base

# curl for uv
RUN apt-get update && apt-get install -y --no-install-recommends \
  git \
  sqlite3 \
  curl \
  build-essential \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# --- Builder Stage ---
FROM base AS builder

# RUN mkdir -p -m 0700 /root/.ssh && \
# ssh-keyscan github.com >> /root/.ssh/known_hosts

# RUN --mount=type=ssh git clone --recurse-submodules git@github.com:upa/llmexp-chatbot.git .
COPY . /app

RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"

# ENV N_PREFIX="$HOME/n"
RUN curl -L https://bit.ly/n-install | bash -s -- -y -
RUN cat $HOME/.bashrc
RUN /bin/bash $HOME/.bashrc
ENV PATH="/root/n/bin:$PATH"
RUN which n
RUN n 22 && npm install -g pnpm@latest

RUN $HOME/.local/bin/uv sync
RUN . .venv/bin/activate

# --- Final Stage ---
FROM base AS final

WORKDIR /app

COPY --from=builder /app /app

COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]

CMD ["/app/.venv/bin/chainlit", "run", "app.py", "--host", "0.0.0.0", "--port", "8000"]
