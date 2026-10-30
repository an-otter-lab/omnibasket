import { TestBed } from '@angular/core/testing';
import { AppComponent } from './app.component';
import { I18nService, LANG_KEY, browserLang } from './i18n';
import { MESSAGES } from './messages';
import { SettingsComponent } from './settings.component';
import { DARK_QUERY, THEME_KEY, ThemeService } from './theme';

// Feature 8: the RO/EN toggle and the system / light / dark theme.

function clean(): void {
  localStorage.removeItem(LANG_KEY);
  localStorage.removeItem(THEME_KEY);
  const root = document.documentElement;
  root.lang = 'en';
  delete root.dataset['theme'];
  delete root.dataset['themePref'];
}

function pressed(el: HTMLElement): string[] {
  return [...el.querySelectorAll<HTMLButtonElement>('button[aria-pressed="true"]')].map((b) => b.textContent!.trim());
}

describe('language (feature 8)', () => {
  beforeEach(clean);
  afterEach(clean);

  it('follows the browser: ro* is Romanian, anything else English', () => {
    expect(browserLang({ language: 'ro-RO' })).toBe('ro');
    expect(browserLang({ language: 'ro' })).toBe('ro');
    expect(browserLang({ language: 'en-GB' })).toBe('en');
    expect(browserLang({ language: 'de-DE' })).toBe('en');
    expect(browserLang({ language: '' })).toBe('en');
  });

  it('starts from the browser language when nothing is saved', () => {
    spyOnProperty(navigator, 'language').and.returnValue('ro-RO');
    const i18n = TestBed.inject(I18nService);
    expect(i18n.lang()).toBe('ro');
    expect(document.documentElement.lang).toBe('ro');
  });

  it('a saved choice wins over the browser language', () => {
    spyOnProperty(navigator, 'language').and.returnValue('ro-RO');
    localStorage.setItem(LANG_KEY, 'en');
    expect(TestBed.inject(I18nService).lang()).toBe('en');
  });

  it('the toggle switches the copy and <html lang>, and is remembered', async () => {
    spyOnProperty(navigator, 'language').and.returnValue('en-US');
    spyOn(globalThis, 'fetch').and.resolveTo({ ok: true, json: async () => ({}) } as Response);
    window.location.hash = '';
    const fixture = TestBed.createComponent(AppComponent);
    fixture.detectChanges();
    await fixture.whenStable();
    const el: HTMLElement = fixture.nativeElement;
    const box = () => el.querySelector('input[name="q"]')!.getAttribute('placeholder');
    expect(box()).toBe(MESSAGES.en.boxPlaceholder);
    expect(pressed(el)).toContain('EN');

    el.querySelector<HTMLButtonElement>('button[lang="ro"]')!.click();
    fixture.detectChanges();
    expect(box()).toBe(MESSAGES.ro.boxPlaceholder);
    expect(el.querySelector('app-photo-input .btn2')!.textContent!.trim()).toBe(MESSAGES.ro.photoButtonFull);
    expect(pressed(el)).toContain('RO');
    expect(document.documentElement.lang).toBe('ro');
    expect(localStorage.getItem(LANG_KEY)).toBe('ro');

    // A new page load (a fresh injector) keeps Romanian although the browser says English.
    TestBed.resetTestingModule();
    expect(TestBed.inject(I18nService).lang()).toBe('ro');

    fixture.destroy();
  });
});

interface FakeQuery {
  matches: boolean;
  media: string;
  listeners: ((e: { matches: boolean }) => void)[];
  addEventListener: (type: string, fn: (e: { matches: boolean }) => void) => void;
  removeEventListener: (type: string, fn: (e: { matches: boolean }) => void) => void;
}

function fakeMatchMedia(dark: boolean): FakeQuery {
  const q: FakeQuery = {
    matches: dark,
    media: DARK_QUERY,
    listeners: [],
    addEventListener: (_t, fn) => q.listeners.push(fn),
    removeEventListener: (_t, fn) => (q.listeners = q.listeners.filter((f) => f !== fn)),
  };
  spyOn(window, 'matchMedia').and.callFake((query: string) => {
    expect(query).toBe(DARK_QUERY);
    return q as unknown as MediaQueryList;
  });
  return q;
}

function flip(q: FakeQuery, dark: boolean): void {
  q.matches = dark;
  q.listeners.forEach((fn) => fn({ matches: dark }));
}

const bodyBg = () => getComputedStyle(document.body).backgroundColor;
const LIGHT_BG = 'rgb(255, 255, 255)';
const DARK_BG = 'rgb(21, 22, 20)'; // --surface #151614

describe('theme (feature 8)', () => {
  beforeEach(clean);
  afterEach(clean);

  it('system is the default and follows the device, live', () => {
    const q = fakeMatchMedia(false);
    const theme = TestBed.inject(ThemeService);
    expect(theme.pref()).toBe('system');
    expect(document.documentElement.dataset['theme']).toBe('light');
    expect(bodyBg()).toBe(LIGHT_BG);
    flip(q, true);
    expect(theme.theme()).toBe('dark');
    expect(document.documentElement.dataset['theme']).toBe('dark');
    expect(bodyBg()).toBe(DARK_BG);
    flip(q, false);
    expect(document.documentElement.dataset['theme']).toBe('light');
  });

  it('system starts dark on a dark device', () => {
    fakeMatchMedia(true);
    TestBed.inject(ThemeService);
    expect(document.documentElement.dataset['theme']).toBe('dark');
    expect(document.documentElement.dataset['themePref']).toBe('system');
  });

  it('light and dark are fixed whatever the device says, and are remembered', () => {
    const q = fakeMatchMedia(true);
    const theme = TestBed.inject(ThemeService);
    theme.choose('light');
    expect(document.documentElement.dataset['theme']).toBe('light');
    expect(localStorage.getItem(THEME_KEY)).toBe('light');
    flip(q, true);
    expect(document.documentElement.dataset['theme']).toBe('light');

    theme.choose('dark');
    flip(q, false);
    expect(document.documentElement.dataset['theme']).toBe('dark');
    expect(bodyBg()).toBe(DARK_BG);
    expect(localStorage.getItem(THEME_KEY)).toBe('dark');

    theme.choose('system');
    expect(document.documentElement.dataset['theme']).toBe('light');
    expect(localStorage.getItem(THEME_KEY)).toBeNull();
  });

  it('a saved theme is applied on load', () => {
    fakeMatchMedia(false);
    localStorage.setItem(THEME_KEY, 'dark');
    TestBed.inject(ThemeService);
    expect(document.documentElement.dataset['theme']).toBe('dark');
  });

  it('the settings buttons set the theme and show which one is on', () => {
    fakeMatchMedia(false);
    const fixture = TestBed.createComponent(SettingsComponent);
    fixture.detectChanges();
    const el: HTMLElement = fixture.nativeElement;
    expect(pressed(el)).toContain(MESSAGES.en.themeSystem);
    el.querySelector<HTMLButtonElement>('button[data-theme-option="dark"]')!.click();
    fixture.detectChanges();
    expect(pressed(el)).toContain(MESSAGES.en.themeDark);
    expect(document.documentElement.dataset['theme']).toBe('dark');
    expect(localStorage.getItem(THEME_KEY)).toBe('dark');
  });
});
