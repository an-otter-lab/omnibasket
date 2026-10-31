import { TestBed } from '@angular/core/testing';
import { AppComponent } from './app.component';
import { BasketService } from './basket.service';
import { EVENT_SOURCE, SourceLike } from './events.service';
import { Candidate } from './live';

// S2: a second add must not cancel the first book's price read. Each book reads on its own and settles on its own.

const A = '9781526605412';
const B = '9780141369365';

class FakeSource implements SourceLike {
  handlers: Record<string, ((e: { data: string }) => void)[]> = {};
  onerror: ((e: unknown) => void) | null = null;
  closed = false;
  constructor(readonly url: string) {}
  addEventListener(name: string, fn: (e: { data: string }) => void): void { (this.handlers[name] ||= []).push(fn); }
  close(): void { this.closed = true; }
  emit(name: string, data: unknown): void { for (const fn of this.handlers[name] || []) fn({ data: JSON.stringify(data) }); }
}

const SHOP = {
  store_id: 'libris', priced: true, excluded: false, selectable: true, not_selectable_code: null, not_selectable_reason: null,
  read_at: '2026-10-30T10:00:00Z', books_listed: 1, failed_reads: [], free_delivery_threshold_cents: 15000,
  delivery_cents: 1500, delivery_known: true, order_fee_cents: 0, currency: 'RON',
};

function livePayload(isbn: string, title: string, price: number) {
  const id = 'book-' + isbn;
  return {
    currency: 'RON', shops: [SHOP], failed_reads: [],
    books: [{ item_id: id, title, isbn13: isbn, edition_pin: null, editions: [], assigned_store_id: null,
      shops: [{ store_id: 'libris', status: 'in_plan', price_cents: price, seller_certainty: 'direct', edition: null, listing_url: 'https://www.libris.ro/x' }] }],
    live_offers: [{ store_id: 'libris', status: 'ok', reason: null, price_cents: price, listing_url: 'https://www.libris.ro/x', isbn13: isbn, ranked: true }],
    joined_item_id: id, joined_title: title, joined_isbn13: isbn,
  };
}

const cand = (isbn: string, title: string): Candidate => ({ title, author: 'Author', isbn, cover_url: null, shops: [] });

describe('S2: parallel adds', () => {
  let sources: FakeSource[];

  beforeEach(() => {
    sources = [];
    localStorage.clear();
    window.location.hash = '#/add';
    spyOn(window, 'fetch').and.callFake(async (input: RequestInfo | URL) => {
      const ok = String(input).endsWith('/config');
      return { ok, status: ok ? 200 : 404, json: async () => (ok ? { demo: false } : {}) } as Response;
    });
    TestBed.configureTestingModule({ providers: [{ provide: EVENT_SOURCE, useValue: (url: string) => { const s = new FakeSource(url); sources.push(s); return s; } }] });
  });

  afterEach(() => { localStorage.clear(); window.location.hash = ''; });

  function boot() {
    const fixture = TestBed.createComponent(AppComponent);
    fixture.detectChanges();
    return { fixture, app: fixture.componentInstance, basket: TestBed.inject(BasketService) };
  }
  const priceOf = (basket: BasketService, isbn: string) => basket.items.find((i) => i.isbn === isbn)?.offers[0]?.price_cents ?? null;

  it('open A, open B, answer A, answer B: both books are priced', () => {
    const { fixture, app, basket } = boot();
    app.pickBook(cand(A, 'Book A'));
    app.pickBook(cand(B, 'Book B'));
    fixture.detectChanges();
    expect(sources.length).toBe(2);
    expect(sources[0].url).toContain('isbn13=' + A);
    expect(sources[1].url).toContain('isbn13=' + B);
    expect(sources[0].closed).toBe(false); // B's add did not cancel A's read

    sources[0].emit('solution', livePayload(A, 'Book A', 4500));
    sources[1].emit('solution', livePayload(B, 'Book B', 3900));
    fixture.detectChanges();

    expect(basket.items.map((i) => i.isbn)).toEqual([A, B]);
    expect(priceOf(basket, A)).toBe(4500);
    expect(priceOf(basket, B)).toBe(3900);
    expect(app.addError).toBeFalsy();
  });

  it('answers in the other order, and a failed read for A removes only A, with its message', () => {
    const { fixture, app, basket } = boot();
    app.pickBook(cand(A, 'Book A'));
    app.pickBook(cand(B, 'Book B'));
    sources[1].emit('solution', livePayload(B, 'Book B', 3900));
    sources[0].onerror!({});
    fixture.detectChanges();

    expect(basket.items.map((i) => i.isbn)).toEqual([B]);
    expect(priceOf(basket, B)).toBe(3900);
    expect(app.addError).toContain('Book A');
  });

  it('leaving the app closes every read still open', () => {
    const { fixture } = boot();
    const app = fixture.componentInstance;
    app.pickBook(cand(A, 'Book A'));
    app.pickBook(cand(B, 'Book B'));
    fixture.destroy();
    expect(sources.every((s) => s.closed)).toBe(true);
  });
});
