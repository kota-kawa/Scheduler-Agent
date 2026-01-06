FROM python:3.12-slim

WORKDIR /app

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Copy dependency definitions
COPY pyproject.toml uv.lock ./

# Create virtual environment outside of /app to avoid bind mount issues
RUN uv venv /venv
# Install dependencies into that environment
RUN uv sync --frozen --no-dev --project-environment /venv

# Copy application code
COPY . .

# Expose port
EXPOSE 5010

# Run application using the virtual environment
ENV PATH="/venv/bin:$PATH"
CMD ["uvicorn", "asgi:app", "--host", "0.0.0.0", "--port", "5010"]

