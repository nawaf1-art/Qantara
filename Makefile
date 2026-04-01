.PHONY: spike-install spike-run spike-run-venv spike-run-lan-venv spike-clean

spike-install:
	pip install -r gateway/transport_spike/requirements.txt

spike-run:
	QANTARA_SPIKE_HOST=$${QANTARA_SPIKE_HOST:-127.0.0.1} QANTARA_SPIKE_PORT=$${QANTARA_SPIKE_PORT:-8765} python3 gateway/transport_spike/server.py

spike-run-venv:
	QANTARA_SPIKE_HOST=$${QANTARA_SPIKE_HOST:-127.0.0.1} QANTARA_SPIKE_PORT=$${QANTARA_SPIKE_PORT:-8765} ./.venv/bin/python gateway/transport_spike/server.py

spike-run-lan-venv:
	QANTARA_SPIKE_HOST=$${QANTARA_SPIKE_HOST:-0.0.0.0} QANTARA_SPIKE_PORT=$${QANTARA_SPIKE_PORT:-8899} ./.venv/bin/python gateway/transport_spike/server.py

spike-clean:
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
