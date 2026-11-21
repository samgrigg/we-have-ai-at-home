FROM python:3.13-slim
RUN pip install --no-cache-dir uv==0.7.13
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PATH="/app/.venv/bin:$PATH"
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev && useradd --create-home household
USER household
EXPOSE 8000
CMD ["uvicorn", "household.api:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
