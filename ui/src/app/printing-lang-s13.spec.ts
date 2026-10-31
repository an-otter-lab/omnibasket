import { TestBed } from '@angular/core/testing';
import { AppComponent } from './app.component';
import { BasketItem, BasketService } from './basket.service';
import { LiveOffer, isbnLang } from './live';

// S13 (D1): an order chip names the printing's language when the shop priced another-language
// printing of the book the shopper picked: Matilda (Puffin, EN) priced by Libris as a RO printing.
const PUFFIN = '9780142402535';
const RO_PRINTING = '9786063321955';

function offer(store_id: string, isbn13: string, other_printing: boolean): LiveOffer {
  return { store_id, status: 'ok', price_cents: 4500, listing_url: null, isbn13, other_printing, ranked: true };
}

async function render(liveOffers: LiveOffer[]): Promise<HTMLElement> {
  const item: BasketItem = { id: 'book-' + PUFFIN, isbn: PUFFIN, title: 'Matilda', author: null, live_offers: liveOffers,
    offers: liveOffers.map((o) => ({ store_id: o.store_id, price_cents: 4500, seller_certainty: 'direct', edition: null, listing_url: null, read_at: null, in_stock: true })) };
  const basket = TestBed.inject(BasketService);
  basket.items = [item];
  basket.shops = ['libris', 'books_express'].map((id) => ({ id, currency: 'RON', free_shipping_threshold_cents: 15000, shipping_fee_cents: 1290, per_order_fee_cents: 0, read_at: null }));
  const line = (store_id: string) => ({
    store_id,
    books: [{ item_id: item.id, title: 'Matilda', isbn13: PUFFIN, edition: null, price_cents: 4500, seller_certainty: 'direct', listing_url: null, read_at: null }],
    books_subtotal_cents: 4500, qualifying_cents: 4500, free_delivery_threshold_cents: null, threshold_crossed: false,
    over_under_threshold_cents: null, short_of_threshold_cents: null, delivery_known: true, delivery_cents: 1290, order_fee_cents: 0, order_total_cents: 5790, read_at: null,
  });
  const shop = (store_id: string) => ({
    store_id, currency: 'RON', priced: true, excluded: false, selectable: true, not_selectable_code: null, not_selectable_reason: null,
    read_at: null, books_listed: 1, failed_reads: [], free_delivery_threshold_cents: null, delivery_cents: 1290, delivery_known: true, order_fee_cents: 0,
  });
  const payload = {
    currency: 'RON', cached: false, read_at_range: { oldest: null, newest: null }, degraded: null,
    shops: [shop('libris'), shop('books_express')],
    books: [{ item_id: item.id, title: 'Matilda', isbn13: PUFFIN, edition_pin: null, editions: [], assigned_store_id: 'libris', shops: [] }],
    failed_reads: [], memberships: [],
    cheapest: { status: 'ranked', reason: null, total_cents: 11580, books_subtotal_cents: 9000, order_count: 2, orders: [line('libris'), line('books_express')], delta_vs_cheapest_cents: 0, not_ranked: [] },
    ['one_' + 'par' + 'cel']: { status: 'not_possible', reason: null, best_store_id: null, answer: null, per_book_delta: [], shops: [] },
    custom: null,
    edition: { pins: {}, unknown_pins: [], status: 'ranked', reason: null, unpinned_total_cents: null, total_cents: null, delta_cents: null, not_ranked: [] },
  };
  spyOn(window, 'fetch').and.callFake(async (url: RequestInfo | URL) => {
    if (String(url).endsWith('/why')) return new Response(JSON.stringify({ text: 'Sentence.', source: 'template' }), { status: 200 });
    return new Response(JSON.stringify(payload), { status: 200 });
  });
  const fixture = TestBed.createComponent(AppComponent);
  await fixture.componentInstance.load();
  fixture.componentInstance.route = { name: 'result', arg: '' };
  fixture.componentInstance.tab = 'cheapest';
  fixture.detectChanges();
  await fixture.whenStable();
  return fixture.nativeElement as HTMLElement;
}

function chips(el: HTMLElement): string[] {
  return Array.from(el.querySelectorAll('.rcards a.chip, a.chip')).map((c) => (c.textContent || '').replace(/\s+/g, ' ').trim());
}

describe('S13: another-language printing on the order chip', () => {
  afterEach(() => { const b = TestBed.inject(BasketService); b.items = []; b.shops = []; localStorage.clear(); });

  it('reads the language from the ISBN group (978 only)', () => {
    expect(isbnLang('9786063321955')).toBe('RO');
    expect(isbnLang('9789735001230')).toBe('RO');
    expect(isbnLang('9786300000124')).toBe('RO');
    expect(isbnLang(PUFFIN)).toBe('EN');
    expect(isbnLang('9783496097426')).toBe('DE');
    expect(isbnLang('9791090636071')).toBeNull(); // 979-10 is not 978-1
    expect(isbnLang(null)).toBeNull();
  });

  it('Matilda (Puffin) priced as a RO printing at Libris: "Matilda · RO" on the Libris chip only', async () => {
    const c = chips(await render([offer('libris', RO_PRINTING, true), offer('books_express', PUFFIN, false)]));
    expect(c).toContain('Matilda · RO');
    expect(c).toContain('Matilda');
    expect(c.filter((x) => x.includes('· RO')).length).toBe(1);
  });

  it('the same language, or a printing whose language is unknown, adds nothing', async () => {
    expect(chips(await render([offer('libris', '9780000000002', true), offer('books_express', '9791090636071', true)]))).toEqual(['Matilda', 'Matilda']);
  });
});
