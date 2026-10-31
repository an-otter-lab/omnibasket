import { TestBed } from '@angular/core/testing';
import { AppComponent } from './app.component';
import { EVENT_SOURCE, SourceLike } from './events.service';

// S25b: a Books-Express address carries the ISBN; the book is still named from its page by /input.
const BX_URL = 'https://www.books-express.ro/bettyville/p/bm,9780143107880';
const ISBN = '9780143107880';

class FakeSource implements SourceLike {
  handlers: Record<string, ((e: { data: string }) => void)[]> = {};
  onerror: ((e: unknown) => void) | null = null;
  closed = false;
  constructor(readonly url: string) {}
  addEventListener(name: string, fn: (e: { data: string }) => void): void {
    (this.handlers[name] ||= []).push(fn);
  }
  close(): void {
    this.closed = true;
  }
}

interface Call {
  url: string;
  init?: RequestInit;
}

describe('S25b: a pasted shop link with an ISBN in it', () => {
  let source: FakeSource | undefined;
  let calls: Call[];
  const realFetch = window.fetch;

  function reply(body: unknown, ok = true, status = 200): void {
    calls = [];
    window.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
      calls.push({ url: String(input), init });
      if (String(input) === '/config') return { ok: true, status: 200, json: async () => ({ demo: false }) } as Response;
      if (String(input).startsWith('/search')) return { ok: true, status: 200, json: async () => SEARCH } as Response;
      return { ok, status, json: async () => body } as Response;
    }) as typeof fetch;
  }

  async function paste(text: string) {
    const fixture = TestBed.createComponent(AppComponent);
    const app = fixture.componentInstance;
    app.route = { name: 'find', arg: text };
    await app.runSearch(text);
    fixture.detectChanges();
    return { fixture, app };
  }

  beforeEach(() => {
    // Isolation: `source` is the last EventSource this suite opened. Without the reset the
    // not-found test passes only when it happens to run before a test that reads live.
    source = undefined;
    TestBed.configureTestingModule({ providers: [{ provide: EVENT_SOURCE, useValue: (url: string) => (source = new FakeSource(url)) }] });
    localStorage.clear();
    window.location.hash = '';
    window.fetch = realFetch;
  });

  afterEach(() => {
    window.fetch = realFetch;
    window.location.hash = '';
    localStorage.clear();
  });

  const SEARCH = { results: [{ title: 'bm,', author: null, isbn: ISBN, cover_url: null, shops: [] }] };

  it('is named from the page by one /input read, with no ISBN search', async () => {
    reply({
      type: 'link',
      status: 'resolved',
      isbn13: ISBN,
      structured_query: { title: 'Bettyville', author: 'George Hodgman', language: null },
      shop_context: { shop_id: 'books_express', product_url: BX_URL },
      candidates: [],
    });
    const { fixture, app } = await paste(BX_URL);
    const el: HTMLElement = fixture.nativeElement;
    const reads = calls.filter((c) => c.url === '/input');
    expect(reads.length).toBe(1);
    expect(JSON.parse(String(reads[0].init!.body))).toEqual({ raw_input: BX_URL });
    expect(calls.some((c) => c.url.startsWith('/search'))).toBeFalse();
    expect(app.route.name).toBe('add');
    expect(el.querySelector('[data-live="added"]')!.textContent).toContain('Bettyville');
    expect(source!.url).toContain('listing=' + encodeURIComponent(BX_URL));
  });

  it('a page that names no book falls back to the ISBN in the address', async () => {
    reply({ type: 'link', status: 'not_found', isbn13: null, candidates: [], message: "I couldn't find a book on that page." });
    const { fixture, app } = await paste(BX_URL);
    const el: HTMLElement = fixture.nativeElement;
    expect(calls.filter((c) => c.url === '/input').length).toBe(1);
    expect(calls.some((c) => c.url === '/search?limit=5&q=' + ISBN)).toBeTrue();
    expect(el.querySelector('[data-state="link-failed"]')).toBeNull();
    expect(app.candidates.map((c) => c.isbn)).toEqual([ISBN]);
  });

  it('a refused read falls back to the ISBN search, not an error', async () => {
    reply({ error: 'limit', message: 'Too many pasted links today. Try again tomorrow.' }, false, 429);
    const { fixture, app } = await paste(BX_URL);
    const el: HTMLElement = fixture.nativeElement;
    expect(el.querySelector('[data-state="search-error"]')).toBeNull();
    expect(app.candidates.map((c) => c.isbn)).toEqual([ISBN]);
  });
});
