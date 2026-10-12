import type { Config } from "./types";
import { postHit, getCount, mockFetch } from "./api";

/**
 * OAD (Offline/Mock) Mode: enabled via Vite build-time env flag or `?oad`
 * query parameter at runtime. When active, no real network requests are made.
 *
 * Requirements: 8.9
 */
export const IS_OAD =
  (import.meta.env.VITE_OAD_MODE === "true") ||
  new URLSearchParams(window.location.search).get("oad") === "1";

/**
 * Loads the runtime configuration from `/config.json`.
 * In OAD mode, returns a synthetic config without a network request.
 *
 * Requirements: 8.2
 */
export async function loadConfig(): Promise<Config> {
  if (IS_OAD) {
    return { apiUrl: "mock://local" };
  }
  const res = await fetch("/config.json", { cache: "no-store", signal: AbortSignal.timeout(5000) });
  if (!res.ok) throw new Error("Configuration unavailable");
  const config = await res.json();
  if (!config || typeof config.apiUrl !== "string") throw new Error("Missing apiUrl");
  const url = new URL(config.apiUrl);
  if (url.protocol !== "https:" && !(url.protocol === "http:" && url.hostname === "localhost")) {
    throw new Error("Invalid API URL");
  }
  return { apiUrl: config.apiUrl.replace(/\/+$/, "") };
}

/**
 * Formats a counter value using Brazilian Portuguese locale conventions.
 * e.g. 1234567 → "1.234.567"
 *
 * Requirements: 8.6
 */
export function formatCount(n: number): string {
  return new Intl.NumberFormat("pt-BR").format(n);
}

/**
 * Puts the UI into a loading or non-loading state:
 * - Sets `#counter-display` to "Carregando..." while loading
 * - Disables `#refresh-btn` while loading
 * - Toggles `data-loading` attribute on `<body>` for CSS hooks
 * - Clears `#status-message` when starting a load
 *
 * Requirements: 8.7
 */
export function setLoading(isLoading: boolean): void {
  const display = document.getElementById("counter-display")!;
  const btn = document.getElementById("refresh-btn") as HTMLButtonElement;
  const status = document.getElementById("status-message")!;

  if (isLoading) {
    display.textContent = "Carregando...";
    btn.disabled = true;
    status.textContent = "Carregando contagem...";
  } else {
    btn.disabled = false;
  }

  document.body.setAttribute("data-loading", isLoading ? "true" : "false");
}

/**
 * Displays a successfully retrieved count in `#counter-display` and
 * clears any previous status message.
 *
 * Requirements: 8.6, 8.7
 */
export function setCount(count: number): void {
  document.getElementById("counter-display")!.textContent = formatCount(count);
  document.getElementById("status-message")!.textContent = "";
}

/**
 * Displays an error state: resets the counter display to "–" and shows
 * `message` in the `#status-message` aria-live region.
 *
 * Requirements: 8.7
 */
export function setError(message: string): void {
  document.getElementById("counter-display")!.textContent = "–";
  document.getElementById("status-message")!.textContent = message;
}

/**
 * Module-level guard that ensures exactly one POST /hit is sent per page
 * load, regardless of how many times sendHit() is called.
 *
 * Requirements: 8.3, 8.4
 */
let hitSent = false;

/**
 * Sends a single POST /hit to register a page access, then updates the
 * displayed count. The `hitSent` guard prevents any second call from
 * reaching the API.
 *
 * Does NOT retry on timeout (Req 8.10).
 *
 * Requirements: 8.3, 8.4, 8.10
 */
export async function sendHit(config: Config): Promise<void> {
  if (hitSent) return;
  hitSent = true;

  setLoading(true);
  try {
    const data = IS_OAD
      ? await mockFetch("POST")
      : await postHit(config.apiUrl);
    setCount(data.count);
  } catch {
    setError("Não foi possível registrar o acesso. Tente novamente mais tarde.");
  } finally {
    setLoading(false);
  }
}

/**
 * Fetches the current counter value via GET /count and updates the display.
 * Never calls postHit.
 *
 * Requirements: 8.5
 */
export async function refreshCount(config: Config): Promise<void> {
  setLoading(true);
  try {
    const data = IS_OAD
      ? await mockFetch("GET")
      : await getCount(config.apiUrl);
    setCount(data.count);
  } catch {
    setError(
      "Não foi possível atualizar a contagem. Tente novamente mais tarde."
    );
  } finally {
    setLoading(false);
  }
}

/**
 * Application entry point:
 * 1. Loads runtime config (or shows a config-load error and aborts).
 * 2. Fires a single POST /hit.
 * 3. Attaches the refresh button's click listener.
 *
 * The `hitSent` flag ensures the button click can never trigger a second
 * POST /hit even though the listener is registered with `{ once: false }`.
 *
 * Requirements: 8.2, 8.3, 8.5
 */
let initialized = false;
export async function init(): Promise<void> {
  if (initialized) return;
  initialized = true;
  const year = document.getElementById("footer-year");
  if (year) year.textContent = String(new Date().getFullYear());
  if (IS_OAD) {
    const banner = document.createElement("p");
    banner.id = "mock-banner";
    banner.textContent = "Modo demonstração — dados fictícios, sem conexão com a AWS.";
    document.querySelector("main")?.prepend(banner);
  }
  setLoading(true);
  let config: Config;
  try {
    config = await loadConfig();
  } catch {
    setError(
      "Não foi possível carregar a configuração. Tente novamente mais tarde."
    );
    document.body.setAttribute("data-loading", "false");
    return;
  }

  await sendHit(config);

  document.getElementById("refresh-btn")!.addEventListener(
    "click",
    () => { void refreshCount(config); },
    { once: false }
  );
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", () => { void init(); }, { once: true });
} else {
  void init();
}
