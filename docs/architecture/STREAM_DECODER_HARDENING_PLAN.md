# Stream Decoder Hardening Plan

- Status: Design plan
- Current safeguard: bounded incremental UTF-8 line decoding in `qantara.streaming`

## Current behavior

Qantara’s Ollama, OpenAI-compatible, and generic session adapters consume NDJSON or single-line SSE. The shared decoder preserves multibyte UTF-8 across arbitrary HTTP chunk boundaries and rejects an unterminated line above its configured character ceiling. Parsers ignore malformed/non-object JSON records and treat `[DONE]` as terminal for SSE.

## Remaining debt

- SSE supports fields and multiline data semantics beyond Qantara’s current single-line JSON subset.
- Parser error policy is implicit: malformed records are skipped while oversize records fail the stream.
- Total assistant output limits are enforced by consumers rather than one shared policy object.
- Coverage enumerates important boundaries but is not yet fuzz/property based.

## Proposed work

1. Specify accepted NDJSON and SSE subsets in the agent/backend protocol docs.
2. Introduce a small decoder configuration object for line bytes/chars, total records, total decoded text, and malformed-record policy.
3. Keep transport framing separate from event-schema validation.
4. Add property tests that split valid UTF-8 payloads at every byte boundary and randomly coalesce records.
5. Add fuzz seeds for invalid UTF-8, CR/LF variants, empty fields, huge records, deeply nested JSON, disconnects, and cancellation.
6. Verify every consumer closes or cancels its HTTP response when decoding terminates early.

## Compatibility constraints

- Preserve current public adapter event dictionaries.
- Do not promote reasoning/thinking fields into spoken output.
- Do not buffer a full response solely to parse framing.
- Keep failure messages content-free in default logs.
- Maintain Python 3.11/3.12 and aiohttp compatibility.

## Exit criteria

The decoder can be considered consolidated when all first-party streaming adapters use one configured path, split/coalesced payload properties pass, memory remains bounded under adversarial streams, and cancellation releases the upstream connection promptly.
