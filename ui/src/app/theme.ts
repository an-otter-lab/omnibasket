import { DestroyRef, Injectable, inject, signal } from '@angular/core';

// Feature 8: the colour theme. 'system' (the default) follows the device's
// prefers-color-scheme, live; 'light' and 'dark' are fixed. The choice is kept in
// localStorage. The resolved theme is written to <html data-theme>, which the
// tokens in styles.css key on.
export type ThemePref = 'system' | 'light' | 'dark';
export type Theme = 'light' | 'dark';
export const THEME_KEY = 'omnibasket.theme.v1';
export const DARK_QUERY = '(prefers-color-scheme: dark)';

export function savedTheme(): ThemePref {
  try {
    const v = localStorage.getItem(THEME_KEY);
    return v === 'light' || v === 'dark' ? v : 'system';
  } catch {
    return 'system';
  }
}

@Injectable({ providedIn: 'root' })
export class ThemeService {
  readonly pref = signal<ThemePref>(savedTheme());
  readonly theme = signal<Theme>('light');
  private readonly query: MediaQueryList | null =
    typeof window !== 'undefined' && typeof window.matchMedia === 'function' ? window.matchMedia(DARK_QUERY) : null;
  private readonly onChange = () => this.apply();

  constructor() {
    this.query?.addEventListener?.('change', this.onChange);
    inject(DestroyRef).onDestroy(() => this.query?.removeEventListener?.('change', this.onChange));
    this.apply();
  }

  choose(pref: ThemePref): void {
    try {
      if (pref === 'system') localStorage.removeItem(THEME_KEY);
      else localStorage.setItem(THEME_KEY, pref);
    } catch {
      /* Private mode: the choice lasts for this page only. */
    }
    this.pref.set(pref);
    this.apply();
  }

  private apply(): void {
    const pref = this.pref();
    const theme: Theme = pref === 'system' ? (this.query?.matches ? 'dark' : 'light') : pref;
    this.theme.set(theme);
    const root = document.documentElement;
    root.dataset['theme'] = theme;
    root.dataset['themePref'] = pref;
  }
}
