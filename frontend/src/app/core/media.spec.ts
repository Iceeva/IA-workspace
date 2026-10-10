import { isMedia, mediaKind, tooBig } from './media';

describe('media', () => {
  it('reconnaît image, audio et vidéo par type MIME ou extension', () => {
    expect(mediaKind({ name: 'a.PNG' })).toBe('image');
    expect(mediaKind({ name: 'x', type: 'video/mp4' })).toBe('video');
    expect(mediaKind({ name: 'v.webm' })).toBe('video');
    expect(mediaKind({ name: 'v.mp3' })).toBe('audio');
    expect(mediaKind({ name: 'notes.txt' })).toBeNull();
    expect(isMedia({ name: 'clip.mov' })).toBeTrue();
    expect(isMedia({ name: 'rapport.pdf' })).toBeFalse();
  });
  it('refuse au-delà de 64 Mo', () => {
    expect(tooBig({ size: 65 * 1024 * 1024 })).toBeTrue();
    expect(tooBig({ size: 1024 })).toBeFalse();
  });
});
