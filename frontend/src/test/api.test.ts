import { afterEach, describe, expect, it, vi } from 'vitest';
import { api, post } from '../api';

afterEach(() => { vi.unstubAllGlobals(); });

describe('local API errors', () => {
  it('gives a recovery action when the local server cannot be reached', async () => {
    vi.stubGlobal('fetch', vi.fn(() => Promise.reject(new TypeError('Failed to fetch'))));
    await expect(api('/api/demo')).rejects.toThrow('Cannot reach the local PatchProof server. Check that it is running');
  });
  it('does not expose an HTML proxy error as a JSON parser stack', async () => {
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve(new Response('<h1>Gateway unavailable</h1>', { status: 502 }))));
    await expect(api('/api/demo')).rejects.toThrow('The local server returned HTTP 502.');
  });
  it('preserves actionable server validation locations', async () => {
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve(new Response(JSON.stringify({ detail: [{ loc: ['body', 'baseline_prompt'], msg: 'String should have at least 1 character' }] }), { status: 422 }))));
    await expect(post('/api/experiments', {})).rejects.toThrow('body.baseline_prompt: String should have at least 1 character');
  });
  it('reports invalid successful JSON separately from saved experiment state', async () => {
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve(new Response('not JSON', { status: 200 }))));
    await expect(api('/api/experiments')).rejects.toThrow('The local server returned an invalid JSON response.');
  });
  it('keeps the outcome uncertain when a POST response cannot be delivered', async () => {
    vi.stubGlobal('fetch', vi.fn(() => Promise.reject(new TypeError('Failed to fetch'))));
    await expect(post('/api/experiments', {})).rejects.toThrow('The request outcome could not be confirmed. The server may have accepted it.');
    expect(fetch).toHaveBeenCalledTimes(1);
  });
  it.each([200, 202, 502])('retains HTTP %s and outcome uncertainty for an unreadable POST response', async status => {
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve(new Response('<h1>Response delivery interrupted</h1>', { status }))));
    const request = post('/api/experiments/run-1/cancel', {});
    await expect(request).rejects.toThrow(`HTTP ${status}`);
    await expect(request).rejects.toThrow('The server may have accepted it. Check the current state before submitting again; for experiments, inspect status and saved history.');
    expect(fetch).toHaveBeenCalledTimes(1);
  });
});
