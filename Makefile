.PHONY: spike-install spike-run spike-run-venv spike-run-lan-venv fake-backend-run fake-backend-run-venv real-backend-run-venv spike-clean test doctor smoke-test lock lock-check docker-build docker-up docker-down

# Hash-locked CPU speech stack for Python 3.11/3.12 (installs CPU-only torch).
spike-install:
	pip install --require-hashes -r gateway/transport_spike/requirements.txt

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

real-backend-run-venv:
	QANTARA_REAL_BACKEND_HOST=$${QANTARA_REAL_BACKEND_HOST:-127.0.0.1} QANTARA_REAL_BACKEND_PORT=$${QANTARA_REAL_BACKEND_PORT:-19120} QANTARA_OLLAMA_BASE_URL=$${QANTARA_OLLAMA_BASE_URL:-http://127.0.0.1:11434} QANTARA_OLLAMA_MODEL=$${QANTARA_OLLAMA_MODEL:-qwen3.5:2b} ./.venv/bin/python gateway/ollama_session_backend/server.py

spike-clean:
	find . -type d -name __pycache__ -prune -exec rm -rf {} +

test:
	./.venv/bin/python -m unittest discover -s tests -v

# Extra flags go through ARGS, e.g. `make doctor ARGS=--mesh`.
doctor:
	./.venv/bin/python scripts/doctor.py $(ARGS)

smoke-test:
	./.venv/bin/python scripts/smoke_test.py

# Regenerate both hash locks (needs uv); keeps current pins unless ARGS=--upgrade.
lock:
	python3 scripts/lock_requirements.py $(ARGS)

# Verify every locked package has a hash-pinned wheel for each supported platform.
lock-check:
	python3 scripts/check_lock_hashes.py

docker-build:
	docker compose build

docker-up:
	docker compose up

docker-down:
	docker compose down
