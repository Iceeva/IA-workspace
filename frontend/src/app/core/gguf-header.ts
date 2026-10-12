/** Lecture de l'en-tête d'un fichier .gguf DANS LE NAVIGATEUR (§11) : seuls les premiers Mo sont lus, rien n'est envoyé nulle part.
 *  Même logique que backend/app/runtimes/gguf.py (v2/v3, tableaux ignorés). */
const FILE_TYPES: Record<number, string> = { 0: 'F32', 1: 'F16', 2: 'Q4_0', 3: 'Q4_1', 7: 'Q8_0', 8: 'Q5_0', 9: 'Q5_1', 10: 'Q2_K', 11: 'Q3_K_S',
  12: 'Q3_K_M', 13: 'Q3_K_L', 14: 'Q4_K_S', 15: 'Q4_K_M', 16: 'Q5_K_S', 17: 'Q5_K_M', 18: 'Q6_K', 32: 'BF16' };
const QUANT_RE = /(IQ\d_[A-Z]+|Q\d_K_[SML]|Q\d_K|Q\d_\d|BF16|F16|F32|FP16)/i;
const MAX_KV = 200_000, MAX_STR = 1 << 26;
export class GgufError extends Error {}
export class Truncated extends GgufError {}

export interface GgufInfo { fileName: string; sizeBytes: number; sizeGb: number; version: number; tensorCount: number; architecture: string; name: string;
  quantization: string; contextLength: number | null; blockCount: number | null; embeddingLength: number | null; headCount: number | null; headCountKv: number | null;
  capabilities: string[]; memoryNeededGb: number; }

const SCALAR: Record<number, number> = { 0: 1, 1: 1, 2: 2, 3: 2, 4: 4, 5: 4, 6: 4, 7: 1, 10: 8, 11: 8, 12: 8 };

class Reader {
  o = 0; v: DataView; constructor(public buf: ArrayBuffer) { this.v = new DataView(buf); }
  need(n: number) { if (this.o + n > this.buf.byteLength) throw new Truncated('En-tête GGUF tronqué'); }
  u32() { this.need(4); const x = this.v.getUint32(this.o, true); this.o += 4; return x; }
  u64() { this.need(8); const x = this.v.getBigUint64(this.o, true); this.o += 8; if (x > BigInt(Number.MAX_SAFE_INTEGER)) throw new GgufError('Valeur GGUF anormale'); return Number(x); }
  str() { const n = this.u64(); if (n > MAX_STR) throw new GgufError('Chaîne GGUF anormalement longue'); this.need(n);
    const s = new TextDecoder().decode(new Uint8Array(this.buf, this.o, n)); this.o += n; return s; }
  scalar(t: number): number | boolean {
    this.need(SCALAR[t]); const v = this.v, o = this.o; this.o += SCALAR[t];
    switch (t) { case 0: return v.getUint8(o); case 1: return v.getInt8(o); case 2: return v.getUint16(o, true); case 3: return v.getInt16(o, true);
      case 4: return v.getUint32(o, true); case 5: return v.getInt32(o, true); case 6: return v.getFloat32(o, true); case 7: return v.getUint8(o) !== 0;
      case 10: return Number(v.getBigUint64(o, true)); case 11: return Number(v.getBigInt64(o, true)); default: return v.getFloat64(o, true); }
  }
  value(t: number): unknown {
    if (t in SCALAR) return this.scalar(t);
    if (t === 8) return this.str();
    if (t === 9) {
      const et = this.u32(), n = this.u64();
      if (n > 50_000_000) throw new GgufError('Tableau GGUF anormalement grand');
      if (et in SCALAR) { this.need(n * SCALAR[et]); this.o += n * SCALAR[et]; }
      else if (et === 8) { for (let i = 0; i < n; i++) { const l = this.u64(); if (l > MAX_STR) throw new GgufError('Chaîne GGUF anormalement longue'); this.need(l); this.o += l; } }
      else throw new GgufError(`Type de tableau GGUF non géré : ${et}`);
      return null;
    }
    throw new GgufError(`Type GGUF inconnu : ${t}`);
  }
}

export function parseGguf(buf: ArrayBuffer, sizeBytes: number, fileName: string): GgufInfo {
  const r = new Reader(buf);
  if (buf.byteLength < 4 || new TextDecoder().decode(new Uint8Array(buf, 0, 4)) !== 'GGUF') throw new GgufError('Ce fichier n’est pas un GGUF (signature absente)');
  r.o = 4; const version = r.u32();
  if (version !== 2 && version !== 3) throw new GgufError(`Version GGUF non prise en charge : ${version}`);
  const tensors = r.u64(), kvs = r.u64();
  if (kvs > MAX_KV) throw new GgufError('Nombre de métadonnées anormal');
  const meta: Record<string, unknown> = {};
  for (let i = 0; i < kvs; i++) { const k = r.str(); meta[k] = r.value(r.u32()); }
  const arch = String(meta['general.architecture'] ?? 'unknown');
  const g = (k: string) => { const x = meta[`${arch}.${k}`]; return typeof x === 'number' ? x : null; };
  const ft = meta['general.file_type'];
  const quant = (typeof ft === 'number' && FILE_TYPES[ft]) || QUANT_RE.exec(fileName)?.[1]?.toUpperCase() || 'inconnue';
  const name = String(meta['general.name'] || fileName.replace(/\.gguf$/i, ''));
  const info = { fileName, sizeBytes, sizeGb: sizeBytes / 1e9, version, tensorCount: tensors, architecture: arch, name, quantization: quant,
    contextLength: g('context_length'), blockCount: g('block_count'), embeddingLength: g('embedding_length'), headCount: g('attention.head_count'),
    headCountKv: g('attention.head_count_kv'), capabilities: capabilities(`${name} ${fileName}`, arch), memoryNeededGb: 0 };
  info.memoryNeededGb = memoryNeededGb(info);
  return info;
}

export function capabilities(name: string, arch: string): string[] {
  const n = `${name} ${arch}`.toLowerCase();
  if (['bert', 'nomic-bert', 'jina-bert-v2'].includes(arch)) return ['embedding'];
  const caps = ['chat'];
  if (/code|coder|starcoder|deepseek-coder/.test(n)) caps.push('code');
  if (/\bvl\b|vision|llava|moondream|minicpm-v|pixtral/.test(n)) caps.push('vision');
  if (!/instruct|chat|-it\b/.test(n)) return caps.filter(c => c !== 'chat').concat('base-model');
  return caps;
}

/** Poids + cache K/V fp16 + 10 % + 0,5 Go : même estimation que le backend. */
export function memoryNeededGb(i: Pick<GgufInfo, 'sizeBytes' | 'contextLength' | 'blockCount' | 'embeddingLength' | 'headCount' | 'headCountKv'>, ctx?: number): number {
  const c = ctx ?? i.contextLength ?? 4096;
  const kv = i.blockCount && i.embeddingLength && i.headCount
    ? 2 * i.blockCount * c * (i.headCountKv ?? i.headCount) * Math.floor(i.embeddingLength / i.headCount) * 2 : c * 128 * 1024;
  return Math.round(((i.sizeBytes + kv) * 1.1 / 1e9 + 0.5) * 100) / 100;
}

/** Lit l'en-tête d'un File choisi par l'utilisateur : 8 Mo d'abord, puis jusqu'à 96 Mo si le vocabulaire est volumineux. */
export async function readGgufFile(file: File): Promise<GgufInfo> {
  if (!/\.gguf$/i.test(file.name)) throw new GgufError('Extension .gguf attendue');
  for (const mb of [8, 32, 96]) {
    const n = Math.min(file.size, mb * 1024 * 1024);
    try { return parseGguf(await file.slice(0, n).arrayBuffer(), file.size, file.name); }
    catch (e) { if (!(e instanceof Truncated) || n >= file.size) throw e; }
  }
  throw new GgufError('En-tête GGUF trop volumineux');
}

export type Fit = 'gpu_full' | 'gpu_partial' | 'cpu' | 'too_large';
/** Même règle que hardware.fit côté backend. */
export function fit(hw: { vram_mb: number; ram_total_mb: number; ram_available_mb?: number | null }, neededGb: number): Fit {
  const need = neededGb * 1024, avail = hw.ram_available_mb ?? hw.ram_total_mb;
  if (hw.vram_mb >= need) return 'gpu_full';
  if (hw.vram_mb > 0 && hw.vram_mb + avail * 0.8 >= need) return 'gpu_partial';
  return avail * 0.8 >= need ? 'cpu' : 'too_large';
}

/** Commandes pour servir ce fichier ; le chemin est quoté pour le shell (jamais exécuté par l'application). */
export function launchCommands(i: Pick<GgufInfo, 'fileName' | 'contextLength' | 'name'>, ctx?: number): { runtime: string; command: string }[] {
  const q = (s: string) => `'${s.replace(/'/g, `'\\''`)}'`, c = Math.min(ctx ?? i.contextLength ?? 4096, 131072);
  const tag = i.name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'local-model';
  return [
    { runtime: 'llama.cpp', command: `llama-server -m ${q('/chemin/vers/' + i.fileName)} -c ${c} -ngl 99 --port 8080` },
    { runtime: 'Ollama', command: `printf 'FROM %s\\n' ${q('/chemin/vers/' + i.fileName)} > Modelfile && ollama create ${tag} -f Modelfile` },
    { runtime: 'LM Studio', command: `lms import ${q('/chemin/vers/' + i.fileName)}` },
  ];
}
