export function clientToken() {
  return Array.from(crypto.getRandomValues(new Uint8Array(32)), byte => byte.toString(16).padStart(2, '0')).join('');
}

export function safeSourceUrl(value) {
  try { const url = new URL(value); return url.protocol === 'https:' ? url.href : undefined; }
  catch { return undefined; }
}

export function requestPayload(action, values, sessionId, requestId = crypto.randomUUID()) {
  return { ...values, action, request_id: requestId, ...(sessionId ? { session_id: sessionId } : {}) };
}

export async function postChat({ payload, accessCode, ownerToken, fetcher = fetch, pause = ms => new Promise(resolve => setTimeout(resolve, ms)), maxPolls = 240, onProgress = () => {} }) {
  const headers = { 'Content-Type': 'application/json', Authorization: `Bearer ${accessCode}`, 'X-Client-Token': ownerToken };
  let result = await fetcher('/api/chat', { method: 'POST', headers, body: JSON.stringify(payload) });
  let body = await result.json();
  if (result.status !== 202) return { ok: result.ok, status: result.status, body };
  if (!/^[a-f0-9]{64}$/.test(body.job_id || '')) throw new Error('Invalid processing reference');
  const url = `/api/jobs/${body.job_id}`;
  let lastVersion = -1;
  function progress(value) {
    if (typeof value.partial_text === 'string' && value.partial_text.length > 0 && value.partial_text.length <= 5000 && Number.isSafeInteger(value.partial_version) && value.partial_version > lastVersion) {
      lastVersion = value.partial_version; onProgress({ text: value.partial_text, draft: true });
    }
  }
  progress(body);
  for (let attempt = 0; attempt < maxPolls; attempt++) {
    const hint = Number(body.poll_after_ms);
    const delay = result.status === 429 ? 1500 : Number.isFinite(hint) && hint > 0 ? Math.max(500, Math.min(1500, hint)) : 500;
    await pause(delay);
    result = await fetcher(url, { method: 'GET', headers, cache: 'no-store' });
    body = await result.json();
    if (result.status === 202) progress(body);
    if (result.status === 202 || (result.status === 429 && !body.status && !body.error_code)) continue;
    return { ok: result.ok, status: result.status, body };
  }
  // The caller retains the original request ID; checking again does not enqueue another model call.
  throw new Error('Processing still pending');
}
