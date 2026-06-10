// Minimal Qantara converse client. Usage: node converse.mjs "your question"
const resp = await fetch("http://127.0.0.1:8765/api/v1/converse", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ text: process.argv[2] ?? "hello", session_id: "example-node" }),
});
for await (const chunk of resp.body.pipeThrough(new TextDecoderStream())) {
  for (const line of chunk.split("\n")) {
    if (line.startsWith("data: ")) {
      const event = JSON.parse(line.slice(6));
      if (event.type === "assistant_text_final") console.log(event.text);
    }
  }
}
