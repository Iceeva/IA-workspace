/** Pièces jointes « média » (image, audio, vidéo) : analysées par /api/multimodal/prepare au lieu d'être indexées comme documents. */
const EXT = /\.(png|jpe?g|webp|gif|wav|mp3|m4a|ogg|flac|mpeg|webm|mp4|mov|m4v|mkv|avi)$/i;
export const MAX_MEDIA_MB = 64;

export function isMedia(f: { name: string; type?: string }): boolean {
  return /^(image|audio|video)\//.test(f.type ?? '') || EXT.test(f.name);
}

export function mediaKind(f: { name: string; type?: string }): 'image' | 'audio' | 'video' | null {
  const m = /^(image|audio|video)\//.exec(f.type ?? '');
  if (m) return m[1] as 'image' | 'audio' | 'video';
  const e = /\.(\w+)$/.exec(f.name)?.[1]?.toLowerCase();
  if (!e) return null;
  if (['png', 'jpg', 'jpeg', 'webp', 'gif'].includes(e)) return 'image';
  if (['wav', 'mp3', 'm4a', 'ogg', 'flac', 'mpeg'].includes(e)) return 'audio';
  return ['webm', 'mp4', 'mov', 'm4v', 'mkv', 'avi'].includes(e) ? 'video' : null;
}

export function tooBig(f: { size: number }): boolean { return f.size > MAX_MEDIA_MB * 1024 * 1024; }
