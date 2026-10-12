import type { CountResponse } from './types';

async function request(apiUrl: string, path: string, method: string): Promise<CountResponse> {
  const response = await fetch(`${apiUrl.replace(/\/+$/, '')}/${path}`, {
    method, cache: 'no-store',
    headers: { 'Content-Type': 'application/json' },
    signal: AbortSignal.timeout(5000),
  });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  const data: unknown = await response.json();
  if (!data || typeof data !== 'object' || !('count' in data) ||
      !Number.isSafeInteger(data.count) || (data.count as number) < 0) {
    throw new Error('Invalid counter response');
  }
  return data as CountResponse;
}
export const postHit = (apiUrl: string) => request(apiUrl, 'hit', 'POST');
export const getCount = (apiUrl: string) => request(apiUrl, 'count', 'GET');
export async function mockFetch(_method: 'POST' | 'GET'): Promise<CountResponse> {
  return { count: 42 };
}
