FROM python:3.11-slim

WORKDIR /app

COPY SERVER/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY SERVER/ .

EXPOSE 8000

CMD ["sh", "-c", "uvicorn server:app --host 0.0.0.0 --port ${PORT:-8000}"]
