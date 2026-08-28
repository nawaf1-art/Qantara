# CLI Launcher

`cli.py` is Qantara's source-checkout launcher. It selects a backend, applies startup configuration, optionally manages the Ollama or OpenClaw bridge, and starts the aiohttp gateway.

The CLI is not installed as a console script by the base wheel in `0.3.1`; use a source checkout for `cli.py`.

## Examples

Mock backend:

```bash
python cli.py --backend mock
```

Direct local OpenAI-compatible server:

```bash
python cli.py \
  --backend http://127.0.0.1:11434 \
  --model qwen3.5:2b
```

Managed Ollama session bridge:

```bash
python cli.py --backend ollama --model qwen3.5:2b
```

Advanced managed OpenClaw bridge:

```bash
python cli.py --backend openclaw --agent main
```

Explicit YAML file:

```bash
python cli.py --config /path/to/qantara.yml
```

## Flags

| Flag | Meaning |
|---|---|
| `--backend` | `mock`, `ollama`, `openclaw`, `openai_compatible`, an HTTP(S) URL, or a custom session-backend value |
| `--model` | Ollama or OpenAI-compatible model identifier |
| `--agent` | OpenClaw agent identifier |
| `--host` | Gateway bind host |
| `--port` | Gateway TCP port |
| `--config` | Explicit `qantara.yml` path |

Backend aliases accepted by the launcher include `openai`, `openai-compatible`, and `openai_compatible`. An HTTP(S) URL selects the direct OpenAI-compatible adapter. An unrecognized non-URL value is treated as a custom session backend value and is passed to the session-contract adapter.

## Startup precedence

For startup values, the implemented precedence is:

```text
environment variables > explicit CLI flags > selected YAML file > built-in defaults
```

This means an existing `QANTARA_SPIKE_PORT`, for example, overrides `--port`. Check the environment when a flag appears to be ignored.

The YAML file is selected in this order:

1. `--config PATH`
2. `QANTARA_CONFIG`
3. `qantara.yml` in the repository root
4. no file

The setup page and `/api/configure` are runtime configuration surfaces. They can replace the active backend binding for the running process, but they do not rewrite environment variables, CLI arguments, or YAML.

## Relevant environment variables

| CLI value | Environment override |
|---|---|
| backend | `QANTARA_BACKEND` |
| model | `QANTARA_OLLAMA_MODEL` |
| agent | `QANTARA_OPENCLAW_AGENT_ID` |
| host | `QANTARA_SPIKE_HOST` |
| port | `QANTARA_SPIKE_PORT` |
| config file | `QANTARA_CONFIG` when `--config` is absent |

The launcher translates its backend choice into the lower-level adapter variables documented in [Configuration](CONFIGURATION.md).

## Managed bridges

`--backend ollama` and `--backend openclaw` start a local bridge subprocess on loopback port `19120`, point the gateway at that bridge, wait briefly for health, and terminate the child during shutdown.

Bridge stdout/stderr is drained but hidden by default. Set `QANTARA_BRIDGE_LOG_OUTPUT=1` only for controlled local diagnostics because backend-controlled output may contain sensitive content.

## Security notes

- Keep the default loopback bind unless a trusted-LAN deployment is configured.
- Set a strong `QANTARA_AUTH_TOKEN` and use HTTPS/WSS before browser access from another device.
- Do not put tokens in CLI arguments, shell history, screenshots, or checked-in YAML.
- Backend URL validation in the setup UI is stricter than arbitrary operator-controlled startup configuration; review every endpoint you configure.
