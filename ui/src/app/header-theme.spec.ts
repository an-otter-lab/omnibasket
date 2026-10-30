import { TestBed } from '@angular/core/testing';
import { AppComponent } from './app.component';
import { THEME_KEY } from './theme';

// The header theme menu must go through ThemeService: persisted under THEME_KEY and
// rendered on <html data-theme>, surviving a reload (same class as the setLang bug).

function clean(): void {
  localStorage.removeItem(THEME_KEY);
  localStorage.removeItem('omnibasket-theme');
  const root = document.documentElement;
  delete root.dataset['theme'];
  delete root.dataset['themePref'];
}

async function boot() {
  spyOn(globalThis, 'fetch').and.resolveTo({ ok: true, json: async () => ({}) } as Response);
  window.location.hash = '';
  const fixture = TestBed.createComponent(AppComponent);
  fixture.detectChanges();
  await fixture.whenStable();
  fixture.detectChanges();
  return fixture;
}

describe('header theme menu persists through ThemeService', () => {
  beforeEach(clean);
  afterEach(clean);

  for (const choice of ['light', 'dark'] as const) {
    it(`choosing ${choice} is stored, rendered, and survives a reload`, async () => {
      const first = await boot();
      const menu = () => first.nativeElement.querySelectorAll('#theme-menu button[role="menuitem"]') as NodeListOf<HTMLButtonElement>;
      const idx = { system: 0, light: 1, dark: 2 }[choice];
      menu()[idx].click();
      first.detectChanges();
      expect(localStorage.getItem(THEME_KEY)).toBe(choice);
      expect(document.documentElement.dataset['theme']).toBe(choice);

      // Reload: new injector, <html> reset to what the pre-paint script would set from storage.
      first.destroy();
      TestBed.resetTestingModule();
      delete document.documentElement.dataset['theme'];
      delete document.documentElement.dataset['themePref'];
      const second = await boot();
      expect(localStorage.getItem(THEME_KEY)).toBe(choice);
      expect(document.documentElement.dataset['theme']).toBe(choice);
      const current = second.nativeElement.querySelectorAll('#theme-menu [aria-current="true"]');
      expect(current.length).toBe(1);
      expect(current[0].parentElement?.querySelectorAll('button')[idx]).toBe(current[0] as Element);
    });
  }
});
