# Browser Client

## Purpose

Qantara's vanilla JavaScript browser voice client. The directory name is
historical; the client is the current public UI. No framework and no build
step: the page script is inline in `index.html`, and the only other file is
`mic-capture-worklet.js` (the AudioWorklet capture module, also loaded as a
plain `<script>` for the ScriptProcessor fallback).

## Run

Run the gateway and open:

```text
http://127.0.0.1:8765/spike
```

From another device (phone, tablet) use the HTTPS address from
`ops/README.md`: browsers only allow the microphone on secure pages
(HTTPS, or `http://localhost` on the gateway machine itself).

The page connects to the WebSocket on the same host that served it:

```text
ws(s)://<page host>/ws
```

so it works both directly (`ws://127.0.0.1:8765/ws`) and behind the HTTPS
reverse proxy (`wss://qantara.local/ws`). Serving this directory from a
separate static file server is not supported.

## Using the page

- The page connects automatically. Press **Start** once: that click unlocks
  audio playback and starts the microphone. Press **Stop** to mute.
- The conversation view shows what you said, Qantara's replies, tool
  activity, and any errors (microphone, transcription, backend or voice
  problems) in plain language.
- **Audio** picks the barge-in behaviour. **Headset** (default) is the most
  reliable way to interrupt Qantara while it talks. **Speakers** raises the
  interruption threshold relative to the echo it measures during playback.
  Chrome 141+ is asked to cancel the page's own playback from the mic
  (`echoCancellation: "all"`); other browsers fall back to standard echo
  cancellation.
- **Voice settings** holds the TTS voice, avatar, playback style and speech
  speed. Speech speed is only sent to the gateway after you change it;
  otherwise the gateway default (`QANTARA_DEFAULT_SPEECH_RATE`) applies.
- **Debug** (collapsed) keeps the manual controls, stat tiles and a bounded
  event log (last 300 entries).
