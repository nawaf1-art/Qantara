FROM python:3.14-slim@sha256:a7fb1e634c4a578f9e0bd6327f11a3cde11b7a9395f48e24360c0988bcc5c2bc

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

RUN python -m pip install \
        "https://files.pythonhosted.org/packages/5d/95/6b5cb3461ea5673ba0995989746db58eb18b91b54dbf331e72f569540946/pip-26.1.2-py3-none-any.whl#sha256=382ff9f685ee3bc25864f820aa50505825f10f5458ffff07e30a6d96e5715cab" \
    && python -m pip install --require-hashes -r /tmp/requirements.txt \
    && python -m pip install \
        "https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl#sha256=1932429db727d4bff3deed6b34cfc05df17794f4a52eeb26cf8928f7c1a0fb85" \
    && groupadd --gid 10001 qantara \
    && useradd --uid 10001 --gid qantara --create-home --shell /usr/sbin/nologin qantara

COPY --chown=qantara:qantara . /app

ENV HOME=/home/qantara \
    XDG_CACHE_HOME=/home/qantara/.cache

USER qantara

EXPOSE 8765 19120

CMD ["python", "gateway/transport_spike/server.py"]
