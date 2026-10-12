import { pushSample, sparklinePath } from './sparkline';

describe('sparkline', () => {
  it('trace de gauche à droite, le maximum en haut', () => {
    const p = sparklinePath([0, 10, 5], 100, 30, 0);
    expect(p).toBe('M0.0,30.0 L50.0,0.0 L100.0,15.0');
  });
  it('tolère série vide, un point, série constante', () => {
    expect(sparklinePath([])).toBe('');
    expect(sparklinePath([4]).startsWith('M3.0,')).toBeTrue();
    expect(sparklinePath([2, 2, 2])).toContain('L');
  });
  it('garde les 60 dernières mesures', () => {
    let s: number[] = []; for (let i = 0; i < 100; i++) s = pushSample(s, i);
    expect(s.length).toBe(60); expect(s[0]).toBe(40); expect(s[59]).toBe(99);
  });
});
