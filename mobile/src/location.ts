import * as Location from 'expo-location';

export type GeoFix = {
  lat: number;
  lng: number;
  accuracy: number | null;
  address: string | null;
};

function formatAddress(place: Location.LocationGeocodedAddress | undefined) {
  if (!place) {
    return null;
  }
  const street = [place.streetNumber, place.street].filter(Boolean).join(' ');
  return street || place.name || null;
}

export async function locateHere(): Promise<GeoFix | 'denied'> {
  const { status } = await Location.requestForegroundPermissionsAsync();
  if (status !== 'granted') {
    return 'denied';
  }
  const position = await Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.Balanced });
  const { latitude, longitude, accuracy } = position.coords;
  const places = await Location.reverseGeocodeAsync({ latitude, longitude }).catch(() => []);
  return {
    lat: latitude,
    lng: longitude,
    accuracy: accuracy ?? null,
    address: formatAddress(places[0]),
  };
}

export function describeFix(fix: GeoFix) {
  const where = fix.address ?? `${fix.lat.toFixed(5)}, ${fix.lng.toFixed(5)}`;
  return fix.accuracy ? `${where} (±${Math.round(fix.accuracy)} m)` : where;
}
