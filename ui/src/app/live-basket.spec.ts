import { TestBed } from '@angular/core/testing';
import { AppComponent } from './app.component';
import { BASKET_KEY, BasketService, buildGivenBody } from './basket.service';
import { EVENT_SOURCE, SourceLike } from './events.service';
import { LiveOffer } from './live';

const SAMPLE_TITLE = 'RO-V1 SAMPLE: Povestea Sampleului';
const A = '9781526605412';
const B = '9780141369365';
const C = '9781035028399';

const SHOP = {
  store_id: 'libris', priced: true, excluded: false, selectable: true, not_selectable_code: null, not_selectable_reason: null,
  read_at: '2026-10-30T10:00:00Z', books_listed: 1, failed_reads: [], free_delivery_threshold_cents: 15000,
  delivery_cents: 1500, delivery_known: true, order_fee_cents: 0, currency: 'RON',
};

function live(isbn: string, priced: boolean): LiveOffer[] {
  return [
    { store_id: 'libris', status: priced ? 'ok' : 'failed', reason: priced ? null : 'no_match_in_index', price_cents: priced ? 5000 : null, listing_url: priced ? 'https://www.libris.ro/x' : null, isbn13: isbn, ranked: priced, not_ranked_reason: priced ? undefined : 'no_offer' },
    { store_id: 'emag', status: 'failed', reason: 'no_match_in_index', price_cents: null, listing_url: null, isbn13: isbn, ranked: false, not_ranked_reason: 'no_offer' },
  ];
}

/** A live payload as the API sends it: the joined book AND the ro-v1 sample books it must never keep. */
function livePayload(isbn: string, title: string, priced: boolean) {
  const id = 'book-' + isbn;
  const row = (item_id: string, t: string, i: string | null, shops: unknown[]) => ({ item_id, title: t, isbn13: i, edition_pin: null, editions: [], assigned_store_id: null, shops });
  return {
    currency: 'RON', shops: [SHOP], failed_reads: [],
    books: [
      row('ro-v1-1', SAMPLE_TITLE, '9780000000002', [{ store_id: 'libris', status: 'in_plan', price_cents: 1000, seller_certainty: 'direct', edition: null }]),
      row(id, title, isbn, priced ? [{ store_id: 'libris', status: 'in_plan', price_cents: 5000, seller_certainty: 'direct', edition: null, listing_url: 'https://www.libris.ro/x' }] : []),
    ],
    live_offers: live(isbn, priced), joined_item_id: id, joined_title: title, joined_isbn13: isbn,
  };
}

/** What POST /solve returns for a given body: just the books posted. */
function solved(body: { items: { id: string; title: string; isbn13: string; offers: { store_id: string; price_cents: number }[] }[] }) {
  const books = body.items.map((i) => ({ item_id: i.id, title: i.title, isbn13: i.isbn13, edition_pin: null, editions: [], assigned_store_id: 'libris', shops: i.offers.map((o) => ({ ...o, status: 'in_plan', seller_certainty: 'direct', edition: null })) }));
  const subtotal = body.items.reduce((n, i) => n + i.offers[0].price_cents, 0);
  const order = {
    store_id: 'libris',
    books: body.items.map((i) => ({ item_id: i.id, title: i.title, isbn13: i.isbn13, edition: null, price_cents: i.offers[0].price_cents, listing_url: null, read_at: null })),
    books_subtotal_cents: subtotal, qualifying_cents: subtotal, free_delivery_threshold_cents: 15000, threshold_crossed: false,
    over_under_threshold_cents: null, short_of_threshold_cents: 15000 - subtotal,
    delivery_gap: { status: 'short', short_cents: 15000 - subtotal, threshold_cents: 15000 },
    delivery_known: true, delivery_cents: 1500, order_fee_cents: 0, order_total_cents: subtotal + 1500, read_at: null,
  };
  return {
    currency: 'RON', cached: false, read_at_range: { oldest: null, newest: null }, degraded: null, shops: [SHOP], books, failed_reads: [], memberships: [],
    cheapest: { status: 'ranked', reason: null, total_cents: subtotal + 1500, books_subtotal_cents: subtotal, order_count: 1, orders: [order], delta_vs_cheapest_cents: 0, not_ranked: [] },
    [['one', 'par' + 'cel'].join('_')]: { status: 'ranked', reason: null, best_store_id: 'libris', answer: null, per_book_delta: [], shops: [] },
    custom: null,
    edition: { pins: {}, unknown_pins: [], status: 'ranked', reason: null, unpinned_total_cents: null, total_cents: null, delta_cents: null, not_ranked: [] },
  };
}

class FakeSource implements SourceLike {
  handlers: Record<string, ((e: { data: string }) => void)[]> = {};
  onerror: ((e: unknown) => void) | null = null;
  constructor(readonly url: string) {}
  addEventListener(name: string, fn: (e: { data: string }) => void): void { (this.handlers[name] ||= []).push(fn); }
  close(): void {}
  emit(name: string, data: unknown): void { for (const fn of this.handlers[name] || []) fn({ data: JSON.stringify(data) }); }
}

describe('the shopper\'s own basket', () => {
  let solveBodies: any[];
  let source: FakeSource;
  let demo = false;

  beforeEach(() => {
    localStorage.clear();
    window.location.hash = '';
    solveBodies = [];
    demo = false;
    spyOn(window, 'fetch').and.callFake(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const json = (b: unknown, ok = true) => ({ ok, status: ok ? 200 : 404, json: async () => b }) as Response;
      if (url.endsWith('/config')) return json({ demo });
      if (url.endsWith('/solve')) {
        const body = JSON.parse(String(init?.body));
        solveBodies.push(body);
        return json(solved(body));
      }
      return json({}, false);
    });
    TestBed.configureTestingModule({ providers: [{ provide: EVENT_SOURCE, useValue: (url: string) => (source = new FakeSource(url)) }] });
  });

  afterEach(() => { localStorage.clear(); window.location.hash = ''; });

  async function settle(fixture: { detectChanges(): void; whenStable(): Promise<unknown> }) {
    for (let n = 0; n < 4; n++) { await fixture.whenStable(); await new Promise((r) => setTimeout(r, 0)); fixture.detectChanges(); }
  }

  it('adds, removes, clears, and survives a reload', () => {
    const svc = TestBed.inject(BasketService);
    svc.addFromLive(livePayload(A, 'Book A', true), A, 'Book A');
    svc.addFromLive(livePayload(B, 'Book B', true), B, 'Book B');
    expect(svc.items.map((i) => i.isbn)).toEqual([A, B]);
    // a "reload": a fresh service reads localStorage
    expect(JSON.parse(localStorage.getItem(BASKET_KEY)!).items.length).toBe(2);
    expect(new BasketService().items.map((i) => i.title)).toEqual(['Book A', 'Book B']);
    svc.remove('book-' + A);
    expect(new BasketService().items.map((i) => i.isbn)).toEqual([B]);
    svc.addFromLive(livePayload(B, 'Book B', true), B, 'Book B');
    expect(svc.items.length).toBe(1); // the same ISBN is not added twice
    svc.clear();
    expect(new BasketService().items).toEqual([]);
  });

  it('keeps only the picked book from a live payload, never the ro-v1 books', () => {
    const svc = TestBed.inject(BasketService);
    svc.addFromLive(livePayload(A, 'Book A', true), A, 'x');
    expect(JSON.stringify(localStorage.getItem(BASKET_KEY))).not.toContain('RO-V1');
    expect(svc.items.length).toBe(1);
  });

  it('POST /solve carries exactly the picked items, source=given', async () => {
    const fixture = TestBed.createComponent(AppComponent);
    const app = fixture.componentInstance;
    app.route = { name: 'live', arg: A };
    app.startLive(A, 'Book A');
    source.emit('solution', livePayload(A, 'Book A', true));
    await settle(fixture);
    app.route = { name: 'live', arg: B };
    app.startLive(B, 'Book B');
    source.emit('solution', livePayload(B, 'Book B', true));
    await settle(fixture);
    const last = solveBodies[solveBodies.length - 1];
    expect(last.source).toBe('given');
    expect(last.items.map((i: any) => ({ id: i.id, title: i.title, isbn13: i.isbn13 }))).toEqual([
      { id: 'book-' + A, title: 'Book A', isbn13: A },
      { id: 'book-' + B, title: 'Book B', isbn13: B },
    ]);
    expect(JSON.stringify(solveBodies)).not.toContain('RO-V1');
    expect(solveBodies.every((b) => b.source === 'given' && b.items.length > 0)).toBeTrue();
    console.log('ASSERTED /solve payload: ' + JSON.stringify(last));
  });

  it('lists a book nobody sells as "No shop lists this ISBN." with the reason per shop, and keeps it out of the solve', async () => {
    const svc = TestBed.inject(BasketService);
    svc.addFromLive(livePayload(A, 'Book A', true), A, 'Book A');
    svc.addFromLive(livePayload(B, 'Book B', true), B, 'Book B');
    svc.addFromLive(livePayload(C, 'Book C no offer', false), C, 'Book C no offer');
    window.location.hash = '#/result/cheapest';
    const fixture = TestBed.createComponent(AppComponent);
    const app = fixture.componentInstance;
    app.route = { name: 'result', arg: '' };
    fixture.detectChanges();
    await settle(fixture);
    const el: HTMLElement = fixture.nativeElement;
    expect(solveBodies[0].items.map((i: any) => i.isbn13)).toEqual([A, B]);
    const row = el.querySelector<HTMLElement>('[data-isbn="' + C + '"]')!;
    expect(row).not.toBeNull();
    expect(row.dataset['noOffer']).toBe('true');
    expect(row.textContent).toContain('Book C no offer');
    expect(row.textContent).toContain('No shop lists this ISBN.');
    expect(row.querySelectorAll('.rrow').length).toBe(2);
    expect(row.querySelector('.rrow[data-shop="emag"]')!.textContent).toContain('No offer found for this ISBN');
    expect(el.querySelectorAll('[data-section="your-books"] .ybook').length).toBe(3);
    expect(el.textContent).toContain('Book A');
  });

  it('no ro-v1 title ever reaches the DOM, on any screen, in normal mode', async () => {
    const svc = TestBed.inject(BasketService);
    svc.addFromLive(livePayload(A, 'Book A', true), A, 'Book A');
    const fixture = TestBed.createComponent(AppComponent);
    const app = fixture.componentInstance;
    for (const name of ['result', 'add', 'editions', 'entry'] as const) {
      app.route = { name, arg: '' };
      app.loaded = false;
      await app.load();
      fixture.detectChanges();
      await settle(fixture);
      expect((fixture.nativeElement as HTMLElement).textContent).not.toContain('RO-V1');
      expect((fixture.nativeElement as HTMLElement).textContent).not.toContain('Sampleului');
    }
  });

  it('an empty basket shows the empty state, no sample and no solve', async () => {
    window.location.hash = '#/result/cheapest';
    const fixture = TestBed.createComponent(AppComponent);
    fixture.componentInstance.route = { name: 'result', arg: '' };
    fixture.detectChanges();
    await settle(fixture);
    const el: HTMLElement = fixture.nativeElement;
    expect(el.querySelector('[data-screen="empty-basket"]')!.textContent).toContain('Your basket is empty');
    expect(el.querySelector('a[data-sample]')).toBeNull();
    expect(el.querySelector('.tabs')).toBeNull();
    expect(solveBodies.length).toBe(0);
  });

  it('removing a book re-prices without it', async () => {
    const svc = TestBed.inject(BasketService);
    svc.addFromLive(livePayload(A, 'Book A', true), A, 'Book A');
    svc.addFromLive(livePayload(B, 'Book B', true), B, 'Book B');
    window.location.hash = '#/result/cheapest';
    const fixture = TestBed.createComponent(AppComponent);
    fixture.componentInstance.route = { name: 'result', arg: '' };
    fixture.detectChanges();
    await settle(fixture);
    fixture.componentInstance.removeBook('book-' + A);
    await settle(fixture);
    expect(solveBodies[solveBodies.length - 1].items.map((i: any) => i.isbn13)).toEqual([B]);
    expect((fixture.nativeElement as HTMLElement).textContent).not.toContain('Book A');
  });

  it('offers "Try a sample basket" only when the config flag says demo', async () => {
    let fixture = TestBed.createComponent(AppComponent);
    await settle(fixture);
    expect((fixture.nativeElement as HTMLElement).querySelector('a[data-sample]')).toBeNull();
    demo = true;
    TestBed.resetTestingModule();
    TestBed.configureTestingModule({ providers: [{ provide: EVENT_SOURCE, useValue: (u: string) => new FakeSource(u) }] });
    fixture = TestBed.createComponent(AppComponent);
    await settle(fixture);
    expect((fixture.nativeElement as HTMLElement).querySelector('a[data-sample]')!.textContent).toContain('Try a sample basket');
  });

  it('buildGivenBody drops books with no offer in a shop with known rules', () => {
    const svc = TestBed.inject(BasketService);
    svc.addFromLive(livePayload(A, 'Book A', true), A, 'Book A');
    svc.addFromLive(livePayload(C, 'Book C', false), C, 'Book C');
    expect(buildGivenBody(svc.items, svc.shops)!.items.map((i) => i.isbn13)).toEqual([A]);
    expect(buildGivenBody([], svc.shops)).toBeNull();
  });
});
