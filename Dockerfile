FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        espeak-ng \
        libgomp1 \
        libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

COPY ops/docker/requirements.txt /tmp/requirements.txt

RUN pip install --index-url https://download.pytorch.org/whl/cpu torch==2.11.0 \
    && pip install -r /tmp/requirements.txt \
    && python -m spacy download en_core_web_sm

COPY . /app

EXPOSE 8765 19120

CMD ["python", "gateway/transport_spike/server.py"]
