# Backend image: FastAPI + python-telegram-bot served by uvicorn.
FROM python:3.12-slim

WORKDIR /app

# Install dependencies first so this layer is cached unless requirements change.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application code (tests and .env are excluded via .dockerignore / not copied).
COPY app ./app

EXPOSE 8000

# No --reload in the image; the token is injected at runtime via the environment.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
