import { Api, Classification, CityContext, Report } from './types';

const CLASSIFY_TIMEOUT_MS = 8_000;
const CONTEXT_TIMEOUT_MS = 6_000;
const REPORT_TIMEOUT_MS = 30_000;

async function fetchWithTimeout(url: string, init: RequestInit, timeoutMs: number) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, { ...init, signal: controller.signal });
  } catch (e) {
    if (controller.signal.aborted) {
      throw new Error(`The server didn't answer within ${timeoutMs / 1000} s.`);
    }
    throw e;
  } finally {
    clearTimeout(timer);
  }
}

async function readJson<T>(res: Response): Promise<T> {
  if (!res.ok) {
    throw new Error(`The server returned ${res.status} ${res.statusText}`.trim());
  }
  return (await res.json()) as T;
}

export function httpApi(baseUrl: string): Api {
  const base = baseUrl.replace(/\/+$/, '');

  return {
    async classify(photo, location) {
      const form = new FormData();
      form.append('image', { uri: photo.uri, name: 'photo.jpg', type: 'image/jpeg' } as unknown as Blob);
      if (location) {
        form.append('lat', String(location.lat));
        form.append('lng', String(location.lng));
      }
      const res = await fetchWithTimeout(`${base}/classify`, { method: 'POST', body: form }, CLASSIFY_TIMEOUT_MS);
      return readJson<Classification>(res);
    },

    async context(label, location) {
      const query = new URLSearchParams({
        label,
        lat: String(location.lat),
        lng: String(location.lng),
      });
      const res = await fetchWithTimeout(`${base}/context?${query.toString()}`, {}, CONTEXT_TIMEOUT_MS);
      return readJson<CityContext>(res);
    },

    async report(request) {
      const res = await fetchWithTimeout(
        `${base}/report`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(request),
        },
        REPORT_TIMEOUT_MS,
      );
      return readJson<Report>(res);
    },
  };
}
