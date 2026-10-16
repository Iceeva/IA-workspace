import { formatResource, summarizeSamples } from './resources';

describe('resources', () => {
  it('1er échantillon = repos, maximum = pic, delta = pic − repos', () => {
    const r = summarizeSamples([{ ram_used_mb: 1000, cpu_percent: 5 }, { ram_used_mb: 5200, cpu_percent: 80 }, { ram_used_mb: 4000, cpu_percent: 40 }]);
    expect(r.baseline['ram_used_mb']).toBe(1000);
    expect(r.peak['ram_used_mb']).toBe(5200);
    expect(r.delta['ram_used_mb']).toBe(4200);
    expect(r.delta['cpu_percent']).toBe(75);
  });
  it('ignore les valeurs non numériques et tolère une série vide', () => {
    expect(summarizeSamples([])).toEqual({ baseline: {}, peak: {}, delta: {} });
    const r = summarizeSamples([{ a: NaN as any, b: 'x' as any }, { vram_used_mb: 800 }]);
    expect(Object.keys(r.peak)).toEqual(['vram_used_mb']);
  });
  it('formate CPU en %, mémoire en Mo ou Go', () => {
    expect(formatResource('cpu_percent', 79.6)).toBe('80 %');
    expect(formatResource('ram_used_mb', 512)).toBe('512 Mo');
    expect(formatResource('vram_used_mb', 6144)).toBe('6.0 Go');
  });
});
