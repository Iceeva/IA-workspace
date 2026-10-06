import { Injectable, effect, signal } from '@angular/core';

export type ThemeMode = 'system' | 'light' | 'dark';

@Injectable({ providedIn: 'root' })
export class ThemeService {
  readonly mode = signal<ThemeMode>((localStorage.getItem('aiw.theme') as ThemeMode) ?? 'system');
  constructor() {
    effect(() => {
      const m = this.mode(), root = document.documentElement;
      m === 'system' ? root.removeAttribute('data-theme') : root.setAttribute('data-theme', m);
      localStorage.setItem('aiw.theme', m);
    });
  }
  set(m: ThemeMode) { this.mode.set(m); }
}
