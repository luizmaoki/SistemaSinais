FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app/services/api
COPY services/api/requirements.txt services/api/requirements.lock ./
RUN pip install --no-cache-dir -r requirements.txt
COPY services/api/ ./
COPY infra/migrations/ /app/infra/migrations/
COPY fixtures/ /app/fixtures/
EXPOSE 8000
CMD ["sh", "-c", "python -m app.cli init && uvicorn app.main:app --host 0.0.0.0 --port 8000 --no-access-log"]


