/** Résumé d'échantillons système (CPU %, RAM Mo, VRAM Mo) pris pendant un benchmark : au repos, pic, écart. */
export type Sample = Record<string, number>;
export interface ResourceSummary { baseline: Sample; peak: Sample; delta: Sample; }

export function summarizeSamples(samples: Sample[]): ResourceSummary {
  const rows = samples.map(s => Object.fromEntries(Object.entries(s ?? {}).filter(([, v]) => typeof v === 'number' && isFinite(v)))).filter(r => Object.keys(r).length);
  if (!rows.length) return { baseline: {}, peak: {}, delta: {} };
  const peak: Sample = {};
  for (const r of rows) for (const [k, v] of Object.entries(r)) peak[k] = Math.max(peak[k] ?? v, v);
  const baseline = rows[0], delta: Sample = {};
  for (const k of Object.keys(peak)) if (k in baseline) delta[k] = Math.round((peak[k] - baseline[k]) * 10) / 10;
  return { baseline, peak, delta };
}

export const LABELS: Record<string, string> = { cpu_percent: 'CPU', ram_used_mb: 'RAM', vram_used_mb: 'VRAM' };
export function formatResource(key: string, v: number): string {
  return key === 'cpu_percent' ? `${Math.round(v)} %` : v >= 1024 ? `${(v / 1024).toFixed(1)} Go` : `${Math.round(v)} Mo`;
}
