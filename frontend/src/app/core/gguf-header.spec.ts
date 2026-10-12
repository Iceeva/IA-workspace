import { GgufError, fit, launchCommands, memoryNeededGb, parseGguf, readGgufFile } from './gguf-header';

function build(kv: [string, number, any][], version = 3): ArrayBuffer {
  const parts: number[] = []; const enc = new TextEncoder();
  const u32 = (n: number) => parts.push(n & 255, (n >> 8) & 255, (n >> 16) & 255, (n >>> 24) & 255);
  const u64 = (n: number) => { u32(n); u32(0); };
  const str = (s: string) => { const b = enc.encode(s); u64(b.length); parts.push(...b); };
  parts.push(...enc.encode('GGUF')); u32(version); u64(7); u64(kv.length);
  for (const [k, t, v] of kv) { str(k); u32(t);
    if (t === 8) str(v); else if (t === 4) u32(v);
    else if (t === 9) { u32(8); u64(v.length); v.forEach((s: string) => str(s)); } }
  return new Uint8Array(parts).buffer;
}
const KV: [string, number, any][] = [['general.architecture', 8, 'qwen3'], ['general.name', 8, 'Qwen3 8B Instruct'], ['general.file_type', 4, 15],
  ['tokenizer.ggml.tokens', 9, ['a', 'bb', 'ccc']], ['qwen3.context_length', 4, 32768], ['qwen3.block_count', 4, 36], ['qwen3.embedding_length', 4, 4096],
  ['qwen3.attention.head_count', 4, 32], ['qwen3.attention.head_count_kv', 4, 8]];

describe('gguf-header', () => {
  it('lit architecture, quantification, contexte et ignore les tableaux', () => {
    const i = parseGguf(build(KV), 5_000_000_000, 'Qwen3-8B-Q4_K_M.gguf');
    expect(i.architecture).toBe('qwen3'); expect(i.quantization).toBe('Q4_K_M'); expect(i.contextLength).toBe(32768);
    expect(i.blockCount).toBe(36); expect(i.capabilities).toEqual(['chat']); expect(i.tensorCount).toBe(7);
    expect(i.memoryNeededGb).toBeGreaterThan(5);
  });
  it('retombe sur le nom de fichier pour la quantification', () => {
    const i = parseGguf(build([['general.architecture', 8, 'llama']]), 1e9, 'x-Q5_K_M.gguf');
    expect(i.quantization).toBe('Q5_K_M'); expect(i.capabilities).toEqual(['base-model']);
  });
  it('refuse un fichier qui n’est pas un GGUF ou tronqué', () => {
    expect(() => parseGguf(new TextEncoder().encode('PK\u0003\u0004zzzz').buffer as ArrayBuffer, 10, 'a.gguf')).toThrowError(GgufError);
    expect(() => parseGguf(build(KV).slice(0, 40), 1e9, 'a.gguf')).toThrow();
    expect(() => parseGguf(build(KV, 1), 1e9, 'a.gguf')).toThrowError(/Version/);
  });
  it('readGgufFile lit un File et refuse une autre extension', async () => {
    const f = new File([build(KV)], 'm-Q4_K_M.gguf');
    expect((await readGgufFile(f)).name).toBe('Qwen3 8B Instruct');
    await expectAsync(readGgufFile(new File(['x'], 'a.bin'))).toBeRejectedWithError(/gguf/);
  });
  it('estime la mémoire et l’ajustement comme le backend', () => {
    expect(memoryNeededGb({ sizeBytes: 5e9, contextLength: 4096, blockCount: null, embeddingLength: null, headCount: null, headCountKv: null })).toBeCloseTo(((5e9 + 4096 * 131072) * 1.1) / 1e9 + 0.5, 1);
    expect(fit({ vram_mb: 24000, ram_total_mb: 32000 }, 10)).toBe('gpu_full');
    expect(fit({ vram_mb: 0, ram_total_mb: 8000 }, 20)).toBe('too_large');
    expect(fit({ vram_mb: 0, ram_total_mb: 32000, ram_available_mb: 20000 }, 10)).toBe('cpu');
  });
  it('quote le chemin dans les commandes de lancement', () => {
    const c = launchCommands({ fileName: "it's.gguf", contextLength: 999999, name: 'My Model!' });
    expect(c[0].command).toContain(`'/chemin/vers/it'\\''s.gguf'`); expect(c[0].command).toContain('-c 131072'); expect(c[1].command).toContain('my-model');
  });
});
