"""Minimal Qantara converse client. Usage: python converse.py "your question" """
import json
import sys

import requests

with requests.post(
    "http://127.0.0.1:8765/api/v1/converse",
    json={"text": sys.argv[1] if len(sys.argv) > 1 else "hello", "session_id": "example-py"},
    stream=True,
) as resp:
    for line in resp.iter_lines():
        if line.startswith(b"data: "):
            event = json.loads(line[6:])
            if event["type"] == "assistant_text_final":
                print(event["text"])
