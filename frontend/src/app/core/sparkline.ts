/** Courbe SVG d'une série (tableau de nombres) dans un cadre w×h ; série vide ou constante tolérées. */
export function sparklinePath(values: number[], w = 160, h = 36, pad = 3): string {
  if (!values.length) return '';
  const lo = Math.min(...values), hi = Math.max(...values), span = hi - lo || 1;
  const step = values.length > 1 ? (w - 2 * pad) / (values.length - 1) : 0;
  return values.map((v, i) => `${i ? 'L' : 'M'}${(pad + i * step).toFixed(1)},${(h - pad - ((v - lo) / span) * (h - 2 * pad)).toFixed(1)}`).join(' ');
}

/** Ajoute une mesure en gardant les `max` dernières. */
export function pushSample(series: number[], v: number, max = 60): number[] {
  return [...series, v].slice(-max);
}
