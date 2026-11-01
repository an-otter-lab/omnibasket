import { TestBed } from '@angular/core/testing';
import { AppComponent } from './app.component';
import { BasketItem, BasketService } from './basket.service';

// P3: in "Your books", Remove stays at the right of each title row, even when a long title wraps (390 px).
const ISBNS = ['9780142402535', '9786060339229', '9789734668465'];

async function render(): Promise<HTMLElement> {
  const basket = TestBed.inject(BasketService);
  basket.items = ISBNS.map((isbn, n): BasketItem => ({
    id: 'book-' + isbn, isbn, title: n === 2 ? 'Charlie and the Chocolate Factory: the complete illustrated edition' : 'Book ' + n, author: null,
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

describe('P3: where Remove sits in Your books', () => {
  afterEach(() => { const b = TestBed.inject(BasketService); b.items = []; b.shops = []; localStorage.clear(); });

  it('keeps Remove on the right of the title row when the title wraps', async () => {
    const el = await render();
    el.style.display = 'block';
    el.style.width = '358px';
    const rows = Array.from(el.querySelectorAll<HTMLElement>('[data-section="your-books"] .ybook > .between'));
    expect(rows.length).toBe(3);
    for (const row of rows) {
      const title = row.querySelector<HTMLElement>('.pt')!.getBoundingClientRect();
      const btn = row.querySelector<HTMLElement>('button.lnk')!.getBoundingClientRect();
      expect(btn.top).toBeLessThan(title.bottom - 1);
      expect(btn.left).toBeGreaterThanOrEqual(title.right - 1);
      expect(btn.right).toBeLessThanOrEqual(row.getBoundingClientRect().right + 1);
    }
    const longTitle = rows[2].querySelector<HTMLElement>('.pt')!;
    expect(longTitle.getBoundingClientRect().height).toBeGreaterThan(parseFloat(getComputedStyle(longTitle).lineHeight) * 1.5);
    el.remove();
  });

  it('keeps the Remove label on one line', async () => {
    const el = await render();
    el.style.display = 'block';
    el.style.width = '358px';
    for (const btn of Array.from(el.querySelectorAll<HTMLElement>('[data-section="your-books"] .ybook > .between button.lnk'))) {
      expect(getComputedStyle(btn).flexShrink).toBe('0');
    }
    el.remove();
  });
});
