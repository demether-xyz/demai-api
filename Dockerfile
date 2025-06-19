FROM tiangolo/uvicorn-gunicorn-fastapi:python3.11

# Set the working directory to /app
WORKDIR /src

# Install Poetry
RUN pip install poetry
ENV POETRY_VIRTUALENVS_CREATE=false

# Copy Poetry files and install dependencies
COPY pyproject.toml /src/
RUN poetry install --no-root --no-interaction --no-ansi

# Copy the rest of the application
COPY src /src