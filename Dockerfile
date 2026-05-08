FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src ./src
COPY tests ./tests
COPY fixtures ./fixtures
COPY scripts ./scripts

ENV PYTHONUNBUFFERED=1
ENV MEMORY_DB_PATH=/data/memory.db

EXPOSE 8080

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8080"]
