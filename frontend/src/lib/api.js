/**
 * Thin API client.
 *
 * Every call goes through `request` so that a backend that is still booting
 * (it answers 503 until the first ingestion pass lands) is reported as a
 * distinguishable `warming` state rather than a generic failure — the UI shows a
 * "first run in flight" screen instead of an error.
 */

const BASE = import.meta.env.VITE_API_BASE ?? '';

export class ApiError extends Error {
  constructor(message, { status, warming = false } = {}) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.warming = warming;
  }
}

async function request(path, { signal, method = 'GET', body } = {}) {
  let res;
  try {
    res = await fetch(`${BASE}${path}`, {
      method,
      signal,
      headers: {
        Accept: 'application/json',
        ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}),
      },
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch (err) {
    if (err.name === 'AbortError') throw err;
    throw new ApiError(
      'Cannot reach the JalDrishti API. Is the backend running on port 8000?',
      { status: 0 },
    );
  }

  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (body?.detail) detail = body.detail;
    } catch {
      /* non-JSON error body; keep the status line */
    }
    throw new ApiError(detail, { status: res.status, warming: res.status === 503 });
  }
  return res.json();
}

/** Append ?date= when the national Time Machine is active. */
const withDate = (path, date) => (date ? `${path}${path.includes('?') ? '&' : '?'}date=${date}` : path);

export const api = {
  system: (opts) => request('/api/system', opts),
  health: (opts) => request('/api/health', opts),
  countrySummary: (date, opts) => request(withDate('/api/country/summary', date), opts),
  locations: (date, opts) => request(withDate('/api/locations', date), opts),
  state: (name, date, opts) =>
    request(withDate(`/api/state/${encodeURIComponent(name)}/locations`, date), opts),
  detail: (id, date, opts) =>
    request(withDate(`/api/location/${encodeURIComponent(id)}/detail`, date), opts),
  timeline: (id, date, opts) =>
    request(withDate(`/api/location/${encodeURIComponent(id)}/timeline`, date), opts),
  replay: (id, date, opts) =>
    request(`/api/location/${encodeURIComponent(id)}/replay?target=${date}`, opts),
  events: (id, opts) =>
    request(`/api/events${id ? `?location_id=${encodeURIComponent(id)}` : ''}`, opts),
  presets: (opts) => request('/api/timemachine/presets', opts),
  refresh: (opts) => request('/api/refresh', { ...opts, method: 'POST' }),

  // Official Government of India data
  officialSummary: (opts) => request('/api/official/summary', opts),
  officialStations: (onlyAlerting = false, opts) =>
    request(`/api/official/stations${onlyAlerting ? '?only_alerting=true' : ''}`, opts),
  officialAlerts: (floodOnly = false, opts) =>
    request(`/api/official/alerts${floodOnly ? '?flood_only=true' : ''}`, opts),
  station: (code, opts) => request(`/api/official/station/${encodeURIComponent(code)}`, opts),
  rivers: (opts) => request('/api/rivers', opts),

  // AI / ML
  aiStatus: (opts) => request('/api/ai/status', opts),
  insights: (date, opts) => request(withDate('/api/insights', date), opts),
  copilot: (question, history, lang, opts) =>
    request('/api/copilot', { ...opts, method: 'POST', body: { question, history, lang } }),
  advisory: (id, opts) =>
    request(`/api/location/${encodeURIComponent(id)}/advisory`, { ...opts, method: 'POST' }),
  simulate: (id, scenario, opts) =>
    request(`/api/location/${encodeURIComponent(id)}/simulate`, {
      ...opts,
      method: 'POST',
      body: scenario,
    }),
};

/** Static map layers are served from /public/geo and cached for the session. */
const geoCache = new Map();

export async function loadGeo(name) {
  if (geoCache.has(name)) return geoCache.get(name);
  const promise = fetch(`/geo/${name}`)
    .then((r) => {
      if (!r.ok) throw new ApiError(`Could not load map layer ${name} (${r.status})`);
      return r.json();
    })
    .catch((err) => {
      geoCache.delete(name); // let a later attempt retry rather than caching the failure
      throw err;
    });
  geoCache.set(name, promise);
  return promise;
}
