import { Api, Classification, CityContext, Report } from './types';

const REPORT_TIMEOUT_MS = 30_000;

async function readJson<T>(res: Response): Promise<T> {
  if (!res.ok) {
    throw new Error(`${res.status} ${res.statusText}`);
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
      const res = await fetch(`${base}/classify`, { method: 'POST', body: form });
      return readJson<Classification>(res);
    },

    async context(label, location) {
      const query = new URLSearchParams({
        label,
        lat: String(location.lat),
        lng: String(location.lng),
      });
      const res = await fetch(`${base}/context?${query.toString()}`);
      return readJson<CityContext>(res);
    },

    async report(request) {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), REPORT_TIMEOUT_MS);
      try {
        const res = await fetch(`${base}/report`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(request),
          signal: controller.signal,
        });
        return await readJson<Report>(res);
      } finally {
        clearTimeout(timer);
      }
    },
  };
}
