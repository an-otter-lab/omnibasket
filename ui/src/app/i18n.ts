import { Injectable, computed, signal } from '@angular/core';
import { Lang, MESSAGES } from './messages';

// Feature 8: the language. The browser's language picks it (ro* gives Romanian,
// anything else English) until the RO/EN toggle is used; the toggle's choice is
// kept in localStorage and wins from then on.
export const LANG_KEY = 'omnibasket.lang.v1';

export function browserLang(nav: Pick<Navigator, 'language'> | undefined = globalThis.navigator): Lang {
  const tag = (nav?.language || '').toLowerCase();
  return tag.startsWith('ro') ? 'ro' : 'en';
}

export function savedLang(): Lang | null {
  try {
    const v = localStorage.getItem(LANG_KEY);
    return v === 'ro' || v === 'en' ? v : null;
  } catch {
    return null;
  }
}

@Injectable({ providedIn: 'root' })
export class I18nService {
  readonly lang = signal<Lang>(savedLang() ?? browserLang());
  readonly m = computed(() => MESSAGES[this.lang()]);

  constructor() {
    this.apply(this.lang());
  }

  /** The toggle: switch and remember. */
  choose(lang: Lang): void {
    try {
      localStorage.setItem(LANG_KEY, lang);
    } catch {
      /* Private mode: the choice lasts for this page only. */
    }
    this.set(lang);
  }

  /** Switch for this page without remembering it. */
  set(lang: Lang): void {
    this.lang.set(lang);
    this.apply(lang);
  }

  private apply(lang: Lang): void {
    if (typeof document !== 'undefined') document.documentElement.lang = lang;
  }
}
