FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY fetch.py count.py ./
RUN mkdir -p /data/Pine/TradingView /data/Indexes /data/Logs /data/Backups
VOLUME ["/data"]

ENTRYPOINT ["python", "fetch.py"]
CMD ["--output", "/data/Pine/TradingView"]
