import { TestBed } from '@angular/core/testing';
import { AppComponent } from './app.component';
import { BasketItem, BasketService } from './basket.service';

// S34: under "Your books, shop by shop" each book is its own block: about 24 px and a divider
// between books, and each book's title row sits close on its own shop card.
const ISBNS = ['9780142402535', '9786060339229', '9789734668465'];

async function render(): Promise<HTMLElement> {
  const basket = TestBed.inject(BasketService);
  basket.items = ISBNS.map((isbn, n): BasketItem => ({
    id: 'book-' + isbn, isbn, title: 'Book ' + n, author: null,
    offers: [{ store_id: 'libris', price_cents: 4500, seller_certainty: 'direct', edition: null, listing_url: null, read_at: null, in_stock: true }],
    live_offers: [{ store_id: 'libris', status: 'ok', price_cents: 4500, listing_url: null, isbn13: isbn, ranked: true }],
  }));
  basket.shops = [{ id: 'libris', currency: 'RON', free_shipping_threshold_cents: 15000, shipping_fee_cents: 1290, per_order_fee_cents: 0, read_at: null }];
  const books = basket.items.map((i) => ({ item_id: i.id, title: i.title, isbn13: i.isbn, edition: null, price_cents: 4500, seller_certainty: 'direct', listing_url: null, read_at: null }));
  const payload = {
    currency: 'RON', cached: false, read_at_range: { oldest: null, newest: null }, degraded: null,
    shops: [{ store_id: 'libris', currency: 'RON', priced: true, excluded: false, selectable: true, not_selectable_code: null, not_selectable_reason: null, read_at: null, books_listed: 3, failed_reads: [], free_delivery_threshold_cents: 15000, delivery_cents: 1290, delivery_known: true, order_fee_cents: 0 }],
    books: books.map((b) => ({ item_id: b.item_id, title: b.title, isbn13: b.isbn13, edition_pin: null, editions: [], assigned_store_id: 'libris', shops: [] })),
    failed_reads: [], memberships: [],
    cheapest: {
      status: 'ranked', reason: null, total_cents: 14790, books_subtotal_cents: 13500, order_count: 1, delta_vs_cheapest_cents: 0, not_ranked: [],
      orders: [{ store_id: 'libris', books, books_subtotal_cents: 13500, qualifying_cents: 13500, free_delivery_threshold_cents: 15000, threshold_crossed: false, over_under_threshold_cents: -1500, short_of_threshold_cents: 1500, delivery_known: true, delivery_cents: 1290, order_fee_cents: 0, order_total_cents: 14790, read_at: null }],
    },
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
  document.body.appendChild(fixture.nativeElement); // computed styles need the element in the document
  return fixture.nativeElement as HTMLElement;
}

describe('S34: Your books, one block per book', () => {
  afterEach(() => { const b = TestBed.inject(BasketService); b.items = []; b.shops = []; localStorage.clear(); });

  it('a 24 px gap and a divider between books, none above the first', async () => {
    const el = await render();
    const blocks = Array.from(el.querySelectorAll<HTMLElement>('[data-section="your-books"] .ybook'));
    expect(blocks.length).toBe(3);
    const first = getComputedStyle(blocks[0]);
    expect(first.borderTopStyle).toBe('none');
    for (const b of blocks.slice(1)) {
      const cs = getComputedStyle(b);
      expect(cs.marginTop).toBe('24px');
      expect(cs.paddingTop).toBe('24px');
      expect(cs.borderTopStyle).toBe('solid');
      expect(cs.borderTopWidth).toBe('1px');
    }
    el.remove();
  });

  it('each title row sits close on its own shop card (8 px), much closer than the next book', async () => {
    const el = await render();
    for (const b of Array.from(el.querySelectorAll<HTMLElement>('[data-section="your-books"] .ybook'))) {
      const card = b.querySelector<HTMLElement>('app-shop-reads')!;
      expect(getComputedStyle(card).display).toBe('block');
      expect(getComputedStyle(card).marginTop).toBe('8px');
    }
    el.remove();
  });
});
