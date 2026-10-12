import { beforeEach, expect, it, vi } from 'vitest';
import fc from 'fast-check';

const response = (body: unknown, ok = true) => ({ ok, status: ok ? 200 : 503, json: async () => body });
let fetchMock: ReturnType<typeof vi.fn>;
beforeEach(() => {
  vi.resetModules();
  document.body.innerHTML = '<main><span id="counter-display" aria-live="polite"></span><button id="refresh-btn"></button><div id="status-message" role="status"></div><span id="footer-year"></span></main>';
  fetchMock = vi.fn(async (url: string) => response(url === '/config.json' ? { apiUrl: 'https://api.example/dev/' } : { count: 1234 }));
  vi.stubGlobal('fetch', fetchMock);
});
async function start() {
  const app = await import('../src/main');
  await app.init();
  await vi.waitFor(() => expect(document.body.dataset.loading).toBe('false'));
  return app;
}
const posts = () => fetchMock.mock.calls.filter((args: unknown[]) => (args[1] as RequestInit)?.method === 'POST');
const gets = () => fetchMock.mock.calls.filter((args: unknown[]) => (args[1] as RequestInit)?.method === 'GET');

it('initializes once and refresh clicks use GET only', async () => {
  const app = await start();
  await app.init();
  for (let i = 0; i < 3; i++) {
    document.getElementById('refresh-btn')!.click();
    await vi.waitFor(() => expect((document.getElementById('refresh-btn') as HTMLButtonElement).disabled).toBe(false));
  }
  expect(posts()).toHaveLength(1);
  expect(gets()).toHaveLength(3);
  expect(document.getElementById('counter-display')!.textContent).toBe('1.234');
  expect(posts()[0][0]).toBe('https://api.example/dev/hit');
});
it('announces pending work and disables refresh', async () => {
  let resolve!: (value: unknown) => void;
  fetchMock.mockImplementation(async (url: string) => url === '/config.json'
    ? response({ apiUrl: 'https://api.example/dev' })
    : new Promise(r => { resolve = r; }));
  await import('../src/main');
  await vi.waitFor(() => expect(posts()).toHaveLength(1));
  expect(document.getElementById('status-message')!.textContent).toContain('Carregando');
  expect((document.getElementById('refresh-btn') as HTMLButtonElement).disabled).toBe(true);
  resolve(response({ count: 1 }));
  await vi.waitFor(() => expect(document.body.dataset.loading).toBe('false'));
});
it('shows POST HTTP failure without retry and recovers with a GET', async () => {
  fetchMock.mockImplementation(async (url: string) => response(url === '/config.json' ? { apiUrl: 'https://api.example' } : { error: 'unavailable' }, url === '/config.json'));
  await start();
  expect(posts()).toHaveLength(1);
  expect(document.getElementById('status-message')!.textContent).toContain('registrar');
  fetchMock.mockResolvedValue(response({ count: 9 }));
  document.getElementById('refresh-btn')!.click();
  await vi.waitFor(() => expect(document.getElementById('counter-display')!.textContent).toBe('9'));
  expect(posts()).toHaveLength(1);
});
it('shows GET network errors', async () => {
  await start();
  fetchMock.mockRejectedValue(new Error('offline'));
  document.getElementById('refresh-btn')!.click();
  await vi.waitFor(() => expect(document.getElementById('status-message')!.textContent).toContain('atualizar'));
});
it('shows missing configuration without attempting an increment', async () => {
  fetchMock.mockResolvedValue(response({}));
  await start();
  expect(posts()).toHaveLength(0);
  expect(document.getElementById('status-message')!.textContent).toContain('configuração');
});
it('labels offline mode and makes no requests', async () => {
  window.history.replaceState({}, '', '/?oad=1');
  await start();
  expect(fetchMock).not.toHaveBeenCalled();
  expect(document.getElementById('mock-banner')!.textContent).toContain('fictícios');
});
it('rejects malformed counter responses', async () => {
  const { getCount } = await import('../src/api');
  for (const count of [-1, 1.5, '10', null]) {
    fetchMock.mockResolvedValue(response({ count }));
    await expect(getCount('https://api.example')).rejects.toThrow('Invalid counter');
  }
});
it('property: locale formatting matches Intl for safe nonnegative integers', async () => {
  const app = await start();
  fc.assert(fc.property(fc.integer({ min: 0, max: Number.MAX_SAFE_INTEGER }), n => {
    expect(app.formatCount(n)).toBe(new Intl.NumberFormat('pt-BR').format(n));
  }));
});
it('properties: any interaction sequence increments once; k refreshes make k GETs using runtime URL', async () => {
  const app = await start();
  await fc.assert(fc.asyncProperty(fc.array(fc.boolean(), { minLength: 1, maxLength: 30 }), async actions => {
    const initialGets = gets().length;
    for (const refresh of actions) {
      if (refresh) await app.refreshCount({ apiUrl: 'https://api.example/dev/' });
      else await app.sendHit({ apiUrl: 'https://api.example/dev/' });
    }
    expect(posts()).toHaveLength(1);
    expect(gets().length - initialGets).toBe(actions.filter(Boolean).length);
    for (const call of [...posts(), ...gets()]) expect(call[0]).toMatch(/^https:\/\/api\.example\/dev\/(hit|count)$/);
  }), { numRuns: 30 });
});

it('does not retry a timed-out increment', async () => {
  fetchMock.mockImplementation(async (url: string) => {
    if (url === '/config.json') return response({ apiUrl: 'https://api.example/dev' });
    throw new DOMException('Timed out', 'TimeoutError');
  });
  const app = await start();
  await app.init();
  await app.sendHit({ apiUrl: 'https://api.example/dev' });
  expect(posts()).toHaveLength(1);
  expect(document.getElementById('status-message')!.textContent).toContain('registrar');
});
