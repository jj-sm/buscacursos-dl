FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY . /app

RUN pip install --no-cache-dir -r requirements.txt

VOLUME ["/data"]

ENTRYPOINT ["python", "scheduler.py"]
