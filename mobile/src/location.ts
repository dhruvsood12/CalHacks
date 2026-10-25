import * as Location from 'expo-location';

export type LocationSource = 'gps' | 'photo' | 'typed';

export type GeoFix = {
  lat: number;
  lng: number;
  accuracy: number | null;
  address: string | null;
  source: LocationSource;
};

type Coordinates = { lat: number; lng: number; accuracy: number | null };

const CITY_SUFFIX = 'San Francisco, CA';
const SF_BOUNDS = { south: 37.63, north: 37.84, west: -122.53, east: -122.34 };

function formatAddress(place: Location.LocationGeocodedAddress | undefined) {
  if (!place) {
    return null;
  }
  const street = place.street ? [place.streetNumber, place.street].filter(Boolean).join(' ') : null;
  const name = place.name && !/^\d+$/.test(place.name) ? place.name : null;
  return street || name || place.city || place.region || null;
}

function inSanFrancisco(lat: number, lng: number) {
  return lat >= SF_BOUNDS.south && lat <= SF_BOUNDS.north && lng >= SF_BOUNDS.west && lng <= SF_BOUNDS.east;
}

async function addressAt(lat: number, lng: number) {
  const places = await Location.reverseGeocodeAsync({ latitude: lat, longitude: lng }).catch(() => []);
  return formatAddress(places[0]);
}

function toNumber(value: unknown): number | null {
  if (typeof value === 'number' && Number.isFinite(value)) {
    return value;
  }
  if (typeof value === 'string') {
    const [numerator, denominator] = value.split('/').map(Number);
    const result = denominator ? numerator / denominator : numerator;
    return Number.isFinite(result) ? result : null;
  }
  return null;
}

function toDegrees(value: unknown): number | null {
  const parts = Array.isArray(value)
    ? value.map(toNumber)
    : typeof value === 'string' && value.includes(',')
      ? value.split(',').map(toNumber)
      : [toNumber(value)];
  if (parts.length === 0 || parts.some((part) => part === null)) {
    return null;
  }
  const [degrees, minutes = 0, seconds = 0] = parts as number[];
  return Math.abs(degrees) + minutes / 60 + seconds / 3600;
}

function signed(degrees: number, ref: unknown, raw: unknown) {
  const negative = ref === 'S' || ref === 'W' || (typeof raw === 'number' && raw < 0);
  return negative ? -degrees : degrees;
}

export function exifCoordinates(exif: Record<string, unknown> | null | undefined): Coordinates | null {
  if (!exif) {
    return null;
  }
  const gps = (exif['{GPS}'] ?? {}) as Record<string, unknown>;
  const rawLat = gps.Latitude ?? exif.GPSLatitude;
  const rawLng = gps.Longitude ?? exif.GPSLongitude;
  const lat = toDegrees(rawLat);
  const lng = toDegrees(rawLng);
  if (lat === null || lng === null || (lat === 0 && lng === 0) || lat > 90 || lng > 180) {
    return null;
  }
  return {
    lat: signed(lat, gps.LatitudeRef ?? exif.GPSLatitudeRef, rawLat),
    lng: signed(lng, gps.LongitudeRef ?? exif.GPSLongitudeRef, rawLng),
    accuracy: toNumber(gps.HPositioningError ?? exif.GPSHPositioningError),
  };
}

export async function photoLocation(exif: Record<string, unknown> | null | undefined): Promise<GeoFix | null> {
  const coordinates = exifCoordinates(exif);
  if (!coordinates) {
    return null;
  }
  return { ...coordinates, address: await addressAt(coordinates.lat, coordinates.lng), source: 'photo' };
}

export async function locateHere(): Promise<GeoFix | 'denied'> {
  const { status } = await Location.requestForegroundPermissionsAsync();
  if (status !== 'granted') {
    return 'denied';
  }
  const position = await Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.Balanced });
  const { latitude, longitude, accuracy } = position.coords;
  return {
    lat: latitude,
    lng: longitude,
    accuracy: accuracy ?? null,
    address: await addressAt(latitude, longitude),
    source: 'gps',
  };
}

export async function geocodeAddress(text: string): Promise<GeoFix | null> {
  const address = text.trim();
  const query = /san francisco|\bsf\b/i.test(address) ? address : `${address}, ${CITY_SUFFIX}`;
  const results = await Location.geocodeAsync(query).catch(() => []);
  const best = results.find((result) => inSanFrancisco(result.latitude, result.longitude));
  if (!best) {
    return null;
  }
  return { lat: best.latitude, lng: best.longitude, accuracy: null, address, source: 'typed' };
}

export const SOURCE_LABEL: Record<LocationSource, string> = {
  gps: 'your location',
  photo: 'from the photo',
  typed: 'address you entered',
};

export function describeFix(fix: GeoFix) {
  const where = fix.address ?? `${fix.lat.toFixed(5)}, ${fix.lng.toFixed(5)}`;
  const accuracy = fix.accuracy ? ` (±${Math.round(fix.accuracy)} m)` : '';
  return `${where}${accuracy} · ${SOURCE_LABEL[fix.source]}`;
}
