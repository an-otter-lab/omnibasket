import { TestBed } from '@angular/core/testing';
import { AppComponent } from './app.component';
import { EVENT_SOURCE, SourceLike } from './events.service';
import { MESSAGES } from './messages';

// S14 (D2): while a search runs, Find book shows the loading state and is disabled; Enter does
// nothing; the button comes back when the search answers.

class FakeSource implements SourceLike {
  onerror: ((e: unknown) => void) | null = null;
  constructor(readonly url: string) {}
  addEventListener(): void {}
  close(): void {}
}

describe('S14: Find book while a search runs', () => {
  let searches: string[];
  let answer: ((r: Response) => void)[];

  beforeEach(() => {
    localStorage.clear();
    window.location.hash = '#/add';
    searches = [];
    answer = [];
    TestBed.configureTestingModule({ providers: [{ provide: EVENT_SOURCE, useValue: (url: string) => new FakeSource(url) }] });
    spyOn(window, 'fetch').and.callFake((url: RequestInfo | URL) => {
      const u = String(url);
      if (!u.includes('/search')) return Promise.resolve(new Response('{}', { status: 404 }));
      searches.push(u);
      return new Promise<Response>((resolve) => answer.push(resolve));
    });
  });
  afterEach(() => {
    localStorage.clear();
    window.location.hash = '';
  });

  async function settle(fixture: { detectChanges(): void; whenStable(): Promise<unknown> }) {
    for (let n = 0; n < 4; n++) { await new Promise((r) => setTimeout(r, 0)); fixture.detectChanges(); await fixture.whenStable(); }
  }

  async function boot(lang: 'en' | 'ro' = 'en') {
    localStorage.setItem('omnibasket.lang.v1', lang);
    const fixture = TestBed.createComponent(AppComponent);
    fixture.detectChanges();
    await settle(fixture); // the #/add hashchange from beforeEach lands first
    const el = fixture.nativeElement as HTMLElement;
    const input = () => el.querySelector<HTMLInputElement>('#entry-inp')!;
    const button = () => el.querySelector<HTMLButtonElement>('form.efield button[type=submit]')!;
    const submit = async (text: string) => {
      input().value = text;
      input().dispatchEvent(new Event('input'));
      el.querySelector<HTMLFormElement>('form.efield')!.dispatchEvent(new Event('submit', { cancelable: true }));
      await settle(fixture);
    };
    return { fixture, el, button, submit };
  }

  it('a second submit during a pending search sends no second request', async () => {
    const { fixture, button, submit } = await boot();
    await submit('Matilda');
    expect(searches.length).toBe(1);
    expect(button().disabled).toBeTrue();
    expect(button().getAttribute('aria-busy')).toBe('true');
    expect(button().textContent!.trim()).toBe(MESSAGES.en.pickSearching);

    await submit('Sapiens'); // Enter in the field, or a forced submit
    expect(searches.length).toBe(1);
    expect(window.location.hash).toBe('#/find/Matilda');

    answer[0](new Response(JSON.stringify({ results: [] }), { status: 200 }));
    await settle(fixture);
    expect(button().disabled).toBeFalse();
    expect(button().textContent!.trim()).toBe(MESSAGES.en.entrySubmit);
  });

  it('comes back after an error too, and shows the RO loading state', async () => {
    const { fixture, button, submit } = await boot('ro');
    await submit('Matilda');
    expect(button().disabled).toBeTrue();
    expect(button().textContent!.trim()).toBe(MESSAGES.ro.pickSearching);
    answer[0](new Response('{}', { status: 500 }));
    await settle(fixture);
    expect(button().disabled).toBeFalse();
    expect(button().textContent!.trim()).toBe(MESSAGES.ro.entrySubmit);
  });
});
