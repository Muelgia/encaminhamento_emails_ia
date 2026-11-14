FROM python:3.14-slim

ENV TZ=America/Sao_Paulo \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY main.py .
COPY src ./src

# config/, data/ e logs/ são montados como volumes (ver docker-compose.yml)
RUN useradd --create-home --uid 1000 robo \
    && mkdir -p /app/config /app/data /app/logs \
    && chown -R robo:robo /app
USER robo

CMD ["python", "main.py", "--loop"]
