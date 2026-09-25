# CLI Launcher

The `qantara` command is Qantara's launcher. It selects a backend, applies startup configuration, optionally manages the Ollama or OpenClaw bridge, and starts the aiohttp gateway. The implementation lives in `qantara/cli.py`.

- Installed package (built from current source): `qantara ...` and `qantara doctor` (also `qantara-doctor`). The `0.3.1` wheel predates these console scripts.
- Source checkout: `python cli.py ...` and `python scripts/doctor.py` are thin shims over the same code.

## Examples

Mock backend:

```bash
qantara --backend mock
```

Direct local OpenAI-compatible server:

```bash
qantara \
  --backend http://127.0.0.1:11434 \
  --model qwen3.5:2b
```

Managed Ollama session bridge:

```bash
qantara --backend ollama --model qwen3.5:2b
```

Advanced managed OpenClaw bridge:

```bash
qantara --backend openclaw --agent main
```

Explicit YAML file:

```bash
qantara --config /path/to/qantara.yml
```

Environment check (Python version vs Kokoro, aiohttp version, configured STT/TTS importability and Piper voices, CPU vs CUDA PyTorch, token/TLS when binding beyond loopback):

```bash
qantara doctor
qantara doctor --mesh        # inspect a running gateway's mesh peers
```

From a source checkout the equivalents are `python scripts/doctor.py [--mesh]` and `make doctor ARGS=--mesh`.

## Flags

| Flag | Meaning |
|---|---|
| `--backend` | `mock`, `ollama`, `openclaw`, `openai_compatible`, an HTTP(S) URL, or a custom session-backend value |
| `--model` | Ollama or OpenAI-compatible model identifier |
| `--agent` | OpenClaw agent identifier |
| `--host` | Gateway bind host |
| `--port` | Gateway TCP port (1-65535) |
| `--config` | Explicit `qantara.yml` path; the file must exist |

Backend aliases accepted by the launcher include `openai`, `openai-compatible`, and `openai_compatible`. An HTTP(S) URL selects the direct OpenAI-compatible adapter. An unrecognized non-URL value is treated as a custom session backend value and is passed to the session-contract adapter.

## Startup precedence

For startup values, the implemented precedence is:

```text
explicit CLI flags > environment variables > selected YAML file > built-in defaults
```

A flag always wins: `--port 9000` overrides an exported `QANTARA_SPIKE_PORT`, and `--model` overrides `QANTARA_OLLAMA_MODEL` / `QANTARA_OPENAI_MODEL`. Without the flag, the environment variable wins over `qantara.yml`.

The YAML file is selected in this order:

1. `--config PATH` (an error if the file does not exist)
2. `QANTARA_CONFIG` (an error if the file does not exist)
3. `qantara.yml` in the current directory
4. `qantara.yml` in the source-checkout root
5. no file

Configuration errors stop startup with exit code 2 and a message naming the source, for example `QANTARA_SPIKE_PORT must be an integer, got 'abc'`. Unknown sections or keys in the YAML file produce a warning and are ignored. Values may be quoted with `"..."` or `'...'`; `#` starts a comment only at the start of a value or after whitespace, so `url: http://host/#frag` keeps its fragment.

The setup page and `/api/configure` are runtime configuration surfaces. They can replace the active backend binding for the running process, but they do not rewrite environment variables, CLI arguments, or YAML.

## Relevant environment variables

| CLI value | Environment variable (used when the flag is absent) |
|---|---|
| backend | `QANTARA_BACKEND` |
| model | `QANTARA_OLLAMA_MODEL` (the OpenAI-compatible adapter also reads `QANTARA_OPENAI_MODEL`) |
| agent | `QANTARA_OPENCLAW_AGENT_ID` |
| host | `QANTARA_SPIKE_HOST` |
| port | `QANTARA_SPIKE_PORT` |
| config file | `QANTARA_CONFIG` when `--config` is absent |

The launcher translates its backend choice into the lower-level adapter variables documented in [Configuration](CONFIGURATION.md). `backend.url` from YAML is applied only when the matching adapter URL variable (`QANTARA_OPENAI_BASE_URL`, `QANTARA_BACKEND_BASE_URL`, or `QANTARA_OLLAMA_BASE_URL`) is not already set.

## Managed bridges

`--backend ollama` and `--backend openclaw` start a local bridge subprocess on loopback port `19120`, point the gateway at that bridge, wait briefly for health, and terminate the child during shutdown.

Bridge stdout/stderr is drained but hidden by default. Set `QANTARA_BRIDGE_LOG_OUTPUT=1` only for controlled local diagnostics because backend-controlled output may contain sensitive content.

## Security notes

- Keep the default loopback bind unless a trusted-LAN deployment is configured.
- A strong `QANTARA_AUTH_TOKEN` is required before binding beyond loopback: the gateway refuses non-loopback requests without one. Use HTTPS/WSS before browser access from another device. `qantara doctor` checks both.
- Do not put tokens in CLI arguments, shell history, screenshots, or checked-in YAML.
- Backend URL validation in the setup UI is stricter than arbitrary operator-controlled startup configuration; review every endpoint you configure.
