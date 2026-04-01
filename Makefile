.PHONY: spike-install spike-run spike-clean

spike-install:
	pip install -r gateway/transport_spike/requirements.txt

spike-run:
	python3 gateway/transport_spike/server.py

spike-clean:
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
