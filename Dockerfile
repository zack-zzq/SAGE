FROM python:3.12-slim

WORKDIR /app

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Copy project files
COPY pyproject.toml uv.lock ./
COPY src/ src/
COPY static/ static/

# Install dependencies
RUN uv sync --no-dev --frozen

# Expose port
EXPOSE 8000

# Run the application
CMD ["uv", "run", "python", "-m", "sage.main"]
