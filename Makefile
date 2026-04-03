.PHONY: spike-install spike-run spike-run-venv spike-run-lan-venv spike-run-logged fake-backend-run fake-backend-run-venv test test-verbose measure-tts spike-clean

spike-install:
	pip install -r gateway/transport_spike/requirements.txt

spike-run:
	QANTARA_SPIKE_HOST=$${QANTARA_SPIKE_HOST:-127.0.0.1} QANTARA_SPIKE_PORT=$${QANTARA_SPIKE_PORT:-8765} python3 gateway/transport_spike/server.py

spike-run-venv:
	QANTARA_SPIKE_HOST=$${QANTARA_SPIKE_HOST:-127.0.0.1} QANTARA_SPIKE_PORT=$${QANTARA_SPIKE_PORT:-8765} ./.venv/bin/python gateway/transport_spike/server.py

spike-run-lan-venv:
	QANTARA_SPIKE_HOST=$${QANTARA_SPIKE_HOST:-0.0.0.0} QANTARA_SPIKE_PORT=$${QANTARA_SPIKE_PORT:-8899} ./.venv/bin/python gateway/transport_spike/server.py

fake-backend-run:
	QANTARA_FAKE_BACKEND_HOST=$${QANTARA_FAKE_BACKEND_HOST:-127.0.0.1} QANTARA_FAKE_BACKEND_PORT=$${QANTARA_FAKE_BACKEND_PORT:-19110} python3 gateway/fake_session_backend/server.py

fake-backend-run-venv:
	QANTARA_FAKE_BACKEND_HOST=$${QANTARA_FAKE_BACKEND_HOST:-127.0.0.1} QANTARA_FAKE_BACKEND_PORT=$${QANTARA_FAKE_BACKEND_PORT:-19110} ./.venv/bin/python gateway/fake_session_backend/server.py

spike-run-logged:
	QANTARA_SESSION_LOG_DIR=logs/sessions \
	QANTARA_ADAPTER=session_gateway_http \
	QANTARA_BACKEND_BASE_URL=http://127.0.0.1:19110 \
	QANTARA_SPIKE_HOST=$${QANTARA_SPIKE_HOST:-127.0.0.1} \
	QANTARA_SPIKE_PORT=$${QANTARA_SPIKE_PORT:-8765} \
	./.venv/bin/python gateway/transport_spike/server.py

test:
	./.venv/bin/python -m pytest tests/ -q

test-verbose:
	./.venv/bin/python -m pytest tests/ -v

measure-tts:
	./.venv/bin/python experiments/measure_tts_latency.py

spike-clean:
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
