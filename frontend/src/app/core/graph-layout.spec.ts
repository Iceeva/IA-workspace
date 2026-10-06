import { layoutGraph } from './graph-layout';

const t = (id: string, depends_on: string[] = []) => ({ id, depends_on });

describe('layoutGraph', () => {
  it('place les tâches par profondeur (cas en diamant)', () => {
    const l = layoutGraph({ a: t('a'), b: t('b'), c: t('c', ['a', 'b']), d: t('d', ['c']) });
    const x = Object.fromEntries(l.wells.map(w => [w.t.id, w.x]));
    expect(x['a']).toBe(x['b']);
    expect(x['c']).toBeGreaterThan(x['a']);
    expect(x['d']).toBeGreaterThan(x['c']);
    expect(l.links.length).toBe(3);
  });
  it('ignore les dépendances inconnues et ne boucle pas sur un cycle', () => {
    expect(() => layoutGraph({ a: t('a', ['zzz']) })).not.toThrow();
    expect(() => layoutGraph({ a: t('a', ['b']), b: t('b', ['a']) })).not.toThrow();
  });
  it('gère un graphe vide', () => { expect(layoutGraph({}).wells).toEqual([]); });
});
