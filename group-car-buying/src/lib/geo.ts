export interface Point {
  lat: number;
  lng: number;
}

/** Great-circle distance in km. Good enough for "nearby city" suggestions without a Maps API call. */
export function haversineKm(a: Point, b: Point): number {
  const R = 6371;
  const rad = (d: number) => (d * Math.PI) / 180;
  const dLat = rad(b.lat - a.lat);
  const dLng = rad(b.lng - a.lng);
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(rad(a.lat)) * Math.cos(rad(b.lat)) * Math.sin(dLng / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(h));
}

export function nearest<T extends Point>(origin: Point, candidates: T[], radiusKm: number, limit = 3): (T & { km: number })[] {
  return candidates
    .map((c) => ({ ...c, km: Math.round(haversineKm(origin, c)) }))
    .filter((c) => c.km > 0 && c.km <= radiusKm)
    .sort((x, y) => x.km - y.km)
    .slice(0, limit);
}
