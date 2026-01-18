FROM node:20-alpine AS frontend

WORKDIR /app

COPY package*.json vite.config.js ./
COPY frontend ./frontend

RUN npm install
RUN npm run build

FROM python:3.12-slim

WORKDIR /app

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Copy dependency definitions
COPY pyproject.toml uv.lock ./

# Create virtual environment outside of /app to avoid bind mount issues
ENV UV_PROJECT_ENVIRONMENT=/venv
ENV VIRTUAL_ENV=/venv
ENV PATH="$VIRTUAL_ENV/bin:$PATH"
RUN uv venv $VIRTUAL_ENV

# Install dependencies into that environment
RUN uv sync --frozen --no-dev --no-install-project

# Copy application code
COPY . .

# Copy built frontend assets
COPY --from=frontend /app/static/spa ./static/spa

# Expose port
EXPOSE 5010

# Run application using the virtual environment
CMD ["uvicorn", "asgi:app", "--host", "0.0.0.0", "--port", "5010"]
