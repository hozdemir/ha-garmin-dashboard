// Route trace projection (no basemap): local equirectangular, aspect kept.

export interface Projected {
  path: string;
  start: [number, number];
  end: [number, number];
  width: number;
  height: number;
}

/**
 * Project [lat, lon] pairs into a box `width` wide, keeping true proportions.
 * Longitude is scaled by cos(mid latitude) so a square block looks square.
 */
export function projectRoute(points: [number, number][], width: number, maxHeight: number, pad = 12): Projected | null {
  if (points.length < 2 || width <= 2 * pad) return null;
  const lats = points.map(([lat]) => lat);
  const lons = points.map(([, lon]) => lon);
  const minLat = Math.min(...lats);
  const maxLat = Math.max(...lats);
  const minLon = Math.min(...lons);
  const maxLon = Math.max(...lons);
  const k = Math.cos((((minLat + maxLat) / 2) * Math.PI) / 180);
  const spanX = (maxLon - minLon) * k || 1e-9;
  const spanY = maxLat - minLat || 1e-9;
  const innerW = width - 2 * pad;
  const scale = Math.min(innerW / spanX, (maxHeight - 2 * pad) / spanY);
  const drawW = spanX * scale;
  const drawH = spanY * scale;
  const offsetX = pad + (innerW - drawW) / 2;
  const height = Math.max(drawH + 2 * pad, 2 * pad + 1);
  const xy = ([lat, lon]: [number, number]): [number, number] => [
    offsetX + (lon - minLon) * k * scale,
    pad + (maxLat - lat) * scale,
  ];
  const projected = points.map(xy);
  const path = projected.map(([x, y], i) => `${i ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`).join("");
  return { path, start: projected[0]!, end: projected[projected.length - 1]!, width, height };
}
