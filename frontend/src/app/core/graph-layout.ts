export interface LayoutTask { id: string; depends_on: string[]; }
export interface Layout<T extends LayoutTask> {
  wells: { t: T; x: number; y: number }[]; links: { key: string; x1: number; y1: number; x2: number; y2: number }[];
  w: number; h: number;
}

/** Colonne = profondeur (plus long chemin) ; ligne = rang dans la colonne. Robuste aux dépendances inconnues. */
export function layoutGraph<T extends LayoutTask>(tasks: Record<string, T>): Layout<T> {
  const ids = Object.keys(tasks), depth: Record<string, number> = {}, visiting = new Set<string>();
  const d = (id: string): number => {
    if (id in depth) return depth[id];
    if (visiting.has(id)) return 0; // cycle : ne boucle pas
    visiting.add(id);
    const deps = tasks[id].depends_on.filter(x => x in tasks);
    const v = deps.length ? 1 + Math.max(...deps.map(d)) : 0;
    visiting.delete(id);
    return (depth[id] = v);
  };
  ids.forEach(d);
  const rows: Record<number, number> = {}, pos: Record<string, { x: number; y: number }> = {};
  const wells = ids.map(id => {
    const c = depth[id], r = (rows[c] = (rows[c] ?? -1) + 1);
    pos[id] = { x: 60 + c * 130, y: 50 + r * 100 };
    return { t: tasks[id], ...pos[id] };
  });
  const links = ids.flatMap(id => tasks[id].depends_on.filter(p => p in pos).map(p =>
    ({ key: p + '>' + id, x1: pos[p].x + 24, y1: pos[p].y, x2: pos[id].x - 24, y2: pos[id].y })));
  const cols = ids.length ? Math.max(...Object.values(depth)) + 1 : 1;
  const maxRows = ids.length ? Math.max(...Object.values(rows)) + 1 : 1;
  return { wells, links, w: 120 + cols * 130, h: 100 + maxRows * 100 };
}
