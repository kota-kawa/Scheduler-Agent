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

# Expose port
EXPOSE 5010

# Run application using the virtual environment
CMD ["uvicorn", "asgi:app", "--host", "0.0.0.0", "--port", "5010"]

