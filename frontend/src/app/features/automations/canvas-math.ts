export interface Pt { x: number; y: number; }
type N = Record<string, any>;

/** Courbe de Bézier horizontale entre deux ports. */
export function linkCurve(x1: number, y1: number, x2: number, y2: number): string {
  const k = Math.max(40, Math.abs(x2 - x1) / 2);
  return `M${x1},${y1} C${x1 + k},${y1} ${x2 - k},${y2} ${x2},${y2}`;
}

/** Position d’un nœud : `ui` (posée à la main, bornée au canvas) sinon la disposition automatique. */
export function cardPositions(nodes: N[], auto: { t: { id: string }; x: number; y: number }[], maxX: number, maxY: number) {
  const a = new Map(auto.map(w => [w.t.id, { x: w.x - 60 + 20, y: w.y - 50 + 20 }]));
  return nodes.filter(n => n['id']).map(n => {
    const u = n['ui'], f = a.get(n['id']) ?? { x: 20, y: 20 };
    const x = typeof u?.x === 'number' ? u.x : f.x, y = typeof u?.y === 'number' ? u.y : f.y;
    return { id: n['id'] as string, type: n['type'] as string, x: Math.max(0, Math.min(maxX, x)), y: Math.max(0, Math.min(maxY, y)) };
  });
}

/** Vrai si ajouter « to dépend de from » est valide : pas d’auto-lien et pas de cycle. */
export function canLink(nodes: N[], from: string, to: string): boolean {
  if (from === to) return false;
  const deps = new Map(nodes.map(n => [n['id'], (n['depends_on'] ?? []) as string[]]));
  const seen = new Set<string>(), stack = [from];          // from ne doit pas dépendre (transitivement) de to
  while (stack.length) { const x = stack.pop()!; if (x === to) return false; if (seen.has(x)) continue; seen.add(x); stack.push(...(deps.get(x) ?? [])); }
  return true;
}
