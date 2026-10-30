function serverMessage(body: unknown): string {
  if (typeof body === 'string') return body;
  if (Array.isArray(body)) return body.map(item => {
    if (item && typeof item === 'object') {
      const error = item as Record<string, unknown>;
      if (typeof error.msg === 'string') return `${Array.isArray(error.loc) ? error.loc.map(String).join('.') : 'Input'}: ${error.msg}`;
    }
    return serverMessage(item);
  }).join('\n');
  if (body && typeof body === 'object') {
    const record = body as Record<string, unknown>;
    if (Array.isArray(record.errors)) return record.errors.map(String).join('\n');
    if (record.detail !== undefined) return serverMessage(record.detail);
    if (typeof record.message === 'string') return record.message;
  }
  return 'The server could not complete this request. Check the input and try again.';
}
const UNCONFIRMED_POST = 'The request outcome could not be confirmed. The server may have accepted it. Check the current state before submitting again; for experiments, inspect status and saved history.';
export async function api<T>(url: string, options?: RequestInit): Promise<T> {
  const isPost = options?.method?.toUpperCase() === 'POST';
  let response: Response;
  try { response = await fetch(url, options); }
  catch { throw new Error(isPost ? UNCONFIRMED_POST : 'Cannot reach the local PatchProof server. Check that it is running, then try again. Saved experiments remain on the server.'); }
  let body: unknown;
  try { body = await response.json(); }
  catch { throw new Error(isPost ? `The local server returned HTTP ${response.status}, but its JSON response could not be read. ${UNCONFIRMED_POST}` : response.ok ? 'The local server returned an invalid JSON response. Try again or restart the server.' : `The local server returned HTTP ${response.status}. Check that PatchProof is running, then try again.`); }
  if (!response.ok) throw new Error(serverMessage(body));
  return body as T;
}
export function post<T>(url: string, data: unknown): Promise<T> {
  return api<T>(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) });
}
