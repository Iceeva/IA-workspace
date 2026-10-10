import { canLink, cardPositions, linkCurve } from './canvas-math';

describe('canvas-math', () => {
  const ns = [{ id: 'a' }, { id: 'b', depends_on: ['a'] }, { id: 'c', depends_on: ['b'] }];
  it('refuse auto-lien et cycles, accepte les liens valides', () => {
    expect(canLink(ns, 'a', 'a')).toBeFalse();
    expect(canLink(ns, 'c', 'a')).toBeFalse();
    expect(canLink(ns, 'b', 'a')).toBeFalse();
    expect(canLink(ns, 'a', 'c')).toBeTrue();
  });
  it('borne les positions au canvas et utilise la disposition auto sans ui', () => {
    const p = cardPositions([{ id: 'a', ui: { x: 5000, y: -3 } }, { id: 'b' }], [{ t: { id: 'b' }, x: 60, y: 50 }], 750, 410);
    expect([p[0].x, p[0].y]).toEqual([750, 0]);
    expect([p[1].x, p[1].y]).toEqual([20, 20]);
  });
  it('trace une courbe de Bézier', () => expect(linkCurve(0, 0, 100, 50).startsWith('M0,0 C')).toBeTrue());
});
