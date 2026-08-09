# Privacy

Qantara is local-first: it has no Qantara-operated cloud service, analytics SDK, or telemetry endpoint. Privacy still depends on the deployment, speech providers, backend, browser, operating system, and logging choices you configure.

## Data flow

1. The browser captures microphone audio after the user grants permission.
2. PCM16 audio frames travel over the configured WebSocket connection to the gateway.
3. The selected STT provider converts buffered audio to text.
4. Qantara sends the text turn and bounded context to the selected backend adapter.
5. User-facing backend text is sent to the selected TTS provider.
6. PCM audio and display events return to the browser.

With local providers and a local backend, this path can stay on one machine or trusted LAN. If you configure an external endpoint or provider, the data sent to it leaves that boundary under the provider’s own policy.

## What Qantara retains

- Recent audio is held in memory for endpointing/transcription and truncated to a configured limit.
- Session event timelines and transcript snapshots are held in memory with count limits.
- Adapter/bridge conversation histories are bounded in memory for session continuity.
- Qantara does not include a durable transcript database, account profile, analytics store, or telemetry queue.
- Restarting the relevant process clears its in-memory state.

External model servers, agents, reverse proxies, container runtimes, browsers, or operating-system services may retain their own data. Consult and configure those systems separately.

## Browser storage

The browser stores convenience state such as backend type/URL/model, language choices, TTS/voice/avatar preferences, audio mode, speech speed, and random client-session identifiers in `localStorage`. The gateway access token is not stored there; browser login exchanges it for an HttpOnly, SameSite session cookie. The cookie is also marked Secure for direct HTTPS requests and when the reverse proxy reports HTTPS with `X-Forwarded-Proto`.

Backend URLs and model names may themselves be sensitive in some environments. Clear site data in the browser to remove Qantara preferences and continuity identifiers.

## Logs and diagnostics

The default gateway event sink redacts transcripts, assistant text, prompts, activity summaries, tool parameters, and credential-shaped fields. It retains operational fields such as event name, IDs, state, engine, counts, language, and timing.

Managed bridge stdout/stderr is drained but not logged by default. Setting `QANTARA_BRIDGE_LOG_OUTPUT=1` opts into bridge output; that output is controlled by the bridge/backend and may contain sensitive data.

Other components can still log sensitive information, including an operator-supplied event sink, reverse proxy, browser developer tools, model server, agent runtime, container platform, or shell history. Review and redact diagnostics before sharing them.

## Model and dependency downloads

Speech providers may contact upstream model hosts on first use. Docker startup may contact container registries and the Ollama model registry. These requests reveal normal network metadata such as source IP and requested artifacts. Pre-cache and verify artifacts if the deployment must operate without egress; see [Supply chain](SUPPLY_CHAIN.md).

## LAN operation

Loopback is the default privacy boundary. A LAN bind makes Qantara reachable to other devices on that network. Use a strong auth token, HTTPS/WSS, trusted certificates, narrow firewall rules, and a network you control. Direct public-internet exposure is unsupported.

## Removing local Qantara data

- Stop/restart Qantara to clear in-memory gateway and bridge sessions.
- Clear Qantara site data in each browser to remove local preferences and identifiers.
- Remove operator-managed model caches, container volumes, and logs according to their upstream/runtime documentation.
- Rotate auth/admin/mesh tokens if they may have been exposed.

Qantara does not know about or control copies retained by external backends or infrastructure.

## Reporting a concern

Use the private process in [SECURITY.md](../SECURITY.md) for a vulnerability. For a non-security privacy documentation issue, open a public issue without including real transcripts, audio, tokens, private hostnames, or logs.
