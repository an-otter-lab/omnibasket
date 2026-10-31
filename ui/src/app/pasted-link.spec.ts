import { TestBed } from '@angular/core/testing';
import { AppComponent } from './app.component';
import { EVENT_SOURCE, SourceLike } from './events.service';

// R3: the Libris page our own buy list links to. Its address carries no ISBN.
const LIBRIS_URL = 'https://www.libris.ro/carte/matilda-roald-dahl/48068482';
const ISBN = '9786303684956';

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

describe('a pasted shop link with no ISBN in it', () => {
  let source: FakeSource | undefined;
  let calls: Call[];
  const realFetch = window.fetch;

  function reply(body: unknown, ok = true, status = 200): void {
    calls = [];
    window.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
      calls.push({ url: String(input), init });
      if (String(input) === '/config') return { ok: true, status: 200, json: async () => ({ demo: false }) } as Response;
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

  it('a resolved link adds the book and reads the pasted page as its listing', async () => {
    reply({
      type: 'link',
      status: 'resolved',
      isbn13: ISBN,
      structured_query: { title: 'matilda roald dahl', author: 'Roald Dahl', language: null },
      shop_context: { shop_id: 'libris', product_url: LIBRIS_URL },
      candidates: [],
    });
    const { fixture, app } = await paste(LIBRIS_URL);
    const el: HTMLElement = fixture.nativeElement;

    const reads = calls.filter((c) => c.url === '/input');
    expect(reads.length).toBe(1);
    expect(JSON.parse(String(reads[0].init!.body))).toEqual({ raw_input: LIBRIS_URL });

    // R3: no "I couldn't find a book on that page", no empty pick list.
    expect(el.querySelector('[data-state="link-failed"]')).toBeNull();
    // The book joins the basket on the add screen, and its prices are read live.
    expect(app.route.name).toBe('add');
    expect(el.querySelector('[data-live="added"]')!.textContent).toContain('matilda roald dahl');
    expect(source!.url).toContain('isbn13=' + ISBN);
    expect(source!.url).toContain('listing=' + encodeURIComponent(LIBRIS_URL));

    source!.handlers['solution']?.[0]?.({ data: JSON.stringify({ joined_item_id: 'book-' + ISBN, joined_isbn13: ISBN }) });
  });

  it('only a page with no book says it could not find one', async () => {
    reply({ type: 'link', status: 'not_found', isbn13: null, candidates: [], message: "I couldn't find a book on that page." });
    const { fixture } = await paste('https://www.example.com/not-a-book');
    const el: HTMLElement = fixture.nativeElement;
    expect(el.querySelector('[data-state="link-failed"]')!.textContent).toContain("I couldn't find a book on that page.");
    expect(source).toBeUndefined();
  });

  it('a refused read is an error, never the not-found message', async () => {
    reply({ error: 'limit', message: 'Too many pasted links today. Try again tomorrow.' }, false, 429);
    const { fixture } = await paste(LIBRIS_URL);
    const el: HTMLElement = fixture.nativeElement;
    expect(el.querySelector('[data-state="link-failed"]')).toBeNull();
    expect(el.querySelector('[data-state="search-error"]')).not.toBeNull();
  });
});
