FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY backend/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY backend /app/backend
COPY docs /app/docs
RUN mkdir -p /app/data/results
ENV PYTHONPATH=/app
EXPOSE 8000
CMD ["sh", "-c", "cd /app/backend && alembic upgrade head && uvicorn app.api:app --host 0.0.0.0 --port 8000"]
