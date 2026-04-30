# Demo Plan

This plan defines lightweight demo assets for GitHub, Reddit, Hacker News, and short social posts.

## 30-Second Demo Video Script

1. Show the terminal running `docker compose up`.
2. Open `http://localhost:8765`.
3. Select **OpenAI-Compatible** or **Demo**.
4. Enter voice mode and ask one short question.
5. Interrupt the assistant while it is speaking.
6. End on the README with the tagline and repo URL.

Narration:

```text
This is Qantara, a local-first browser voice gateway for Ollama and local AI agents. It handles microphone capture, local speech-to-text, backend streaming, local text-to-speech, playback, and barge-in. The backend stays yours.
```

## 90-Second Technical Demo Script

1. Start Docker and explain the localhost default.
2. Open the setup page and show backend detection.
3. Connect to Ollama through the OpenAI-compatible path.
4. Speak a short prompt to a local model.
5. Interrupt playback and ask a follow-up.
6. Open the debug panel to show backend and latency state.
7. Show `SECURITY.md` or the README privacy section.
8. Mention experimental MCP and Home Assistant/Wyoming paths without overstating them.

## Screenshot List

- README first screen with badges and tagline.
- Setup page with backend options.
- OpenAI-compatible backend configuration.
- Voice mode during an active response.
- Debug panel with latency/backend state.
- Auth token prompt for LAN use.

## GIF List

- Docker start to browser setup page.
- Backend test success.
- Voice conversation with captions.
- Barge-in interruption.
- Switching from setup page to voice mode.

## Recommended Demo Flow

1. Start Docker.
2. Open browser.
3. Connect to Ollama.
4. Speak to local model.
5. Interrupt/barge-in.
6. Show privacy/local-first status.

## Social Preview Recommendation

Use a clean 1280x640 image:

- Left: Qantara name and tagline, "Local-first voice gateway for Ollama and local AI agents".
- Right: simplified flow, "Browser voice -> Qantara -> local LLM/agent".
- Bottom: status labels, "Stable local voice path. Experimental MCP and HA paths."
- Avoid claiming production readiness.
