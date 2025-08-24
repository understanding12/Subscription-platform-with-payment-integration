FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/instance /app/migrations

CMD ["sh", "-c", "flask db upgrade && flask run --host=0.0.0.0 --port=5000"]