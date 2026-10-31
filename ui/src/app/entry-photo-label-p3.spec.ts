import { TestBed } from '@angular/core/testing';
import { AppComponent } from './app.component';
import { EVENT_SOURCE, SourceLike } from './events.service';

// P3: the entry screen's photo file input has an accessible name, like the add-book component's.
class FakeSource implements SourceLike {
  onerror: ((e: unknown) => void) | null = null;
  constructor(readonly url: string) {}
  addEventListener(): void {}
  close(): void {}
}

describe('P3: the entry photo input', () => {
  const realFetch = window.fetch;

  beforeEach(() => {
    TestBed.configureTestingModule({ providers: [{ provide: EVENT_SOURCE, useValue: (url: string) => new FakeSource(url) }] });
    localStorage.clear();
    window.location.hash = '';
    window.fetch = (async () => ({ ok: true, status: 200, json: async () => ({ demo: false }) }) as Response) as typeof fetch;
  });

  afterEach(() => {
    window.fetch = realFetch;
    window.location.hash = '';
    localStorage.clear();
  });

  for (const [lang, label] of [
    ['en', 'Take or choose a photo of a reading list'],
    ['ro', 'Fă sau alege o fotografie a unei liste de cărți'],
  ] as const) {
    it(`is labelled in ${lang}`, () => {
      localStorage.setItem('omnibasket.lang.v1', lang);
      const fixture = TestBed.createComponent(AppComponent);
      fixture.detectChanges();
      const inputs = Array.from((fixture.nativeElement as HTMLElement).querySelectorAll('input[type=file]'));
      expect(inputs.length).toBeGreaterThan(0);
      for (const input of inputs) expect(input.getAttribute('aria-label')).toBe(label);
    });
  }
});
