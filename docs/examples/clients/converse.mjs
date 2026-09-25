// Minimal Qantara converse client (Node 18+). Usage: node converse.mjs "your question"
// Optional: QANTARA_URL (default http://127.0.0.1:8765), QANTARA_AUTH_TOKEN.
const base = (process.env.QANTARA_URL ?? "http://127.0.0.1:8765").replace(/\/+$/, "");
const headers = { "Content-Type": "application/json" };
if (process.env.QANTARA_AUTH_TOKEN) headers.Authorization = `Bearer ${process.env.QANTARA_AUTH_TOKEN}`;

const resp = await fetch(`${base}/api/v1/converse`, {
  method: "POST",
  headers,
  body: JSON.stringify({ text: process.argv[2] ?? "hello", session_id: "example-node" }),
});
if (!resp.ok) {
  console.error(`converse failed: HTTP ${resp.status} ${await resp.text()}`);
  process.exit(1);
}

// SSE events can span network chunks; keep the unfinished tail in a buffer
// and only parse complete lines.
let buffer = "";
const handleLine = (line) => {
  if (!line.startsWith("data: ")) return;
  const event = JSON.parse(line.slice(6));
  if (event.type === "assistant_text_final") console.log(event.text);
};
for await (const chunk of resp.body.pipeThrough(new TextDecoderStream())) {
  buffer += chunk;
  const lines = buffer.split(/\r?\n/);
  buffer = lines.pop();
  lines.forEach(handleLine);
}
if (buffer) handleLine(buffer);
