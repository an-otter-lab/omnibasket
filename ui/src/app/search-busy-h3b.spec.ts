import { TestBed } from '@angular/core/testing';
import { AppComponent } from './app.component';
import { EVENT_SOURCE, SourceLike } from './events.service';

// H3b: a 429 from /search (our own rate limit) shows the same busy message and Try again as a 503.
class FakeSource implements SourceLike {
  onerror: ((e: unknown) => void) | null = null;
  constructor(readonly url: string) {}
  addEventListener(): void {}
  close(): void {}
}

describe('H3b: a rate-limited search', () => {
  const realFetch = window.fetch;
  let searches: string[];
  let answers: number[];

  function serve(...statuses: number[]): void {
    searches = [];
    answers = statuses;
    window.fetch = (async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === '/config') return { ok: true, status: 200, json: async () => ({ demo: false }) } as Response;
      if (url.startsWith('/search')) {
        searches.push(url);
        const status = answers.shift() ?? 200;
        const body = status === 200
          ? { results: [{ title: 'Matilda', author: 'Roald Dahl', isbn: '9780142410370', cover_url: null, shops: [] }] }
          : { error: 'rate limited' };
        return { ok: status === 200, status, json: async () => body } as Response;
      }
      return { ok: false, status: 404, json: async () => ({}) } as Response;
    }) as typeof fetch;
  }

  async function find(text: string, lang: 'en' | 'ro' = 'en') {
    localStorage.setItem('omnibasket.lang.v1', lang);
    const fixture = TestBed.createComponent(AppComponent);
    const app = fixture.componentInstance;
    app.route = { name: 'find', arg: text };
    await app.runSearch(text);
    fixture.detectChanges();
    return { fixture, app, el: fixture.nativeElement as HTMLElement };
  }

  beforeEach(() => {
    TestBed.configureTestingModule({ providers: [{ provide: EVENT_SOURCE, useValue: (url: string) => new FakeSource(url) }] });
    localStorage.clear();
    window.location.hash = '';
  });

  afterEach(() => {
    window.fetch = realFetch;
    window.location.hash = '';
    localStorage.clear();
  });

  it('says the search is busy on a 429, with a Try again button', async () => {
    serve(429);
    const { el } = await find('matilda');
    const box = el.querySelector('[data-state=search-busy]');
    expect(box).not.toBeNull();
    expect(box!.textContent).toContain('Search is busy right now. Try again in a moment.');
    expect(box!.querySelector('button[data-action=retry-search]')!.textContent!.trim()).toBe('Try again');
    expect(el.querySelector('[data-state=search-error]')).toBeNull();
  });

  it('says it in Romanian', async () => {
    serve(429);
    const { el } = await find('matilda', 'ro');
    const box = el.querySelector('[data-state=search-busy]')!;
    expect(box.textContent).toContain('Căutarea este ocupată acum. Încearcă din nou peste câteva clipe.');
    expect(box.querySelector('button')!.textContent!.trim()).toBe('Încearcă din nou');
  });

  it('Try again after a 429 runs the same search and shows the results', async () => {
    serve(429, 200);
    const { fixture, el } = await find('matilda');
    (el.querySelector('button[data-action=retry-search]') as HTMLButtonElement).click();
    await new Promise((r) => setTimeout(r, 0));
    await fixture.whenStable();
    fixture.detectChanges();
    expect(searches.length).toBe(2);
    expect(searches[1]).toBe(searches[0]);
    expect(el.querySelector('[data-state=search-busy]')).toBeNull();
    expect(el.querySelector('button[data-action=pick]')).not.toBeNull();
  });
});
