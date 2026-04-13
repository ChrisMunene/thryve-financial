FROM python:3.12-slim

WORKDIR /app

COPY . .

RUN pip install --no-cache-dir .

CMD ["python", "-m", "app.run_api", "--host", "0.0.0.0", "--port", "8000"]
