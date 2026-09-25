FROM python:3.12-slim@sha256:229a2c5bfa27522db7815ea81f9bed70af17ccb9de9fc7ad142b1877b5830d36

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
        "https://files.pythonhosted.org/packages/f3/6e/1736e5b4ae2b778ef2f81c47d797de9f891d4d8acb047a24ca37a60294dd/pip-26.2.1-py3-none-any.whl#sha256=71138adf1f4ca900cdb7d289c21b7494329f2332b6d85f0e1c42108c0384ed3e" \
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
