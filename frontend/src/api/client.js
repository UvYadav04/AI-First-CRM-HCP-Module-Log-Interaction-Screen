// Talks to the FastAPI backend. Two things live here: a retrying fetch
// wrapper (network resilience) and a manual SSE-over-fetch reader, because
// native EventSource can't send a POST body, which /chat/stream needs.

const API_BASE = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

async function fetchWithRetry(url, options, retries = 2, backoffMs = 500) {
  let lastErr;
  for (let attempt = 0; attempt <= retries; attempt++) {
    try {
      const res = await fetch(url, options);
      if (res.ok || res.status < 500) return res; // don't retry client errors, only network/5xx
      lastErr = new Error(`Request failed: ${res.status}`);
    } catch (err) {
      lastErr = err;
    }
    if (attempt < retries) {
      await new Promise((r) => setTimeout(r, backoffMs * (attempt + 1)));
    }
  }
  throw lastErr;
}

// Per the SSE spec, "data:" is followed by AT MOST one space before the
// real payload - that one space is a delimiter, not part of the content.
// .trim() was stripping the payload's own trailing space too (every token
// is sent as "word ", intentionally, so words don't run together once
// concatenated) - this only strips the single delimiter space, nothing else.
function stripSSEDelimiterSpace(raw) {
  return raw.startsWith(" ") ? raw.slice(1) : raw;
}

function parseSSEChunk(chunk) {
  let event = "message";
  let data = "";
  for (const line of chunk.split("\n")) {
    if (line.startsWith("event:")) event = stripSSEDelimiterSpace(line.slice(6)).trim();
    else if (line.startsWith("data:")) data += stripSSEDelimiterSpace(line.slice(5));
  }
  return data ? { event, data } : null;
}

// onEvent receives {event, data} for each SSE frame: status | token | final | error
export async function streamChat({ threadId, message, onEvent, signal }) {
  const res = await fetchWithRetry(
    `${API_BASE}/chat/stream`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ thread_id: threadId, message }),
      signal,
    },
    1, // only retry the initial connection, not mid-stream
  );

  if (!res.ok || !res.body) {
    throw new Error(`Chat request failed with status ${res.status}`);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    // sse_starlette emits \r\n line endings by default; normalize to \n so
    // frame splitting below is reliable regardless of the server's setting.
    buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n");
    const frames = buffer.split("\n\n");
    buffer = frames.pop(); // keep the trailing partial frame for next read
    for (const frame of frames) {
      const evt = parseSSEChunk(frame);
      if (evt) onEvent(evt);
    }
  }
}

export async function commitInteraction(threadId) {
  const res = await fetchWithRetry(`${API_BASE}/interactions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ thread_id: threadId }),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `Commit failed with status ${res.status}`);
  }
  return res.json();
}
