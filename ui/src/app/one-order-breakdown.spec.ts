import { TestBed } from '@angular/core/testing';
import { AppComponent } from './app.component';
import { BasketService } from './basket.service';

// 3 Nov: "Where the 17,76 comes from" lists each book's price gap and, below them, what delivery and
// order fees save or add, so the rows add up to the amount in the heading (basket A of the demo video).

type App = AppComponent;

function order(store_id: string, books: [string, string, number][], delivery: number, total: number) {
  return {
    store_id, currency: 'RON',
    books: books.map(([item_id, title, price_cents]) => ({ item_id, title, isbn13: null, edition: null, price_cents, currency: 'RON', seller_certainty: 'direct', listing_url: null, read_at: null })),
    books_subtotal_cents: total - delivery, qualifying_cents: total - delivery, free_delivery_threshold_cents: 13500, threshold_crossed: false,
    over_under_threshold_cents: null, short_of_threshold_cents: null, delivery_known: true, delivery_cents: delivery, order_fee_cents: 0,
    order_total_cents: total, read_at: null,
  };
}

function payload(perBook: [number, number, number]) {
  const books: [string, string, number][] = [['b0', 'Jane Eyre', 5572], ['b1', 'The Picture of Dorian Gray', 6000], ['b2', 'Martin Eden', 1600]];
  const cheapest = [3999, 3099, 1600];
  const delta = 1776;
  return {
    currency: 'RON', cached: false, read_at_range: { oldest: null, newest: null }, degraded: null, shops: [], books: [],
    cheapest: { status: 'ranked', reason: null, total_cents: 12686, books_subtotal_cents: 8698, order_count: 2, orders: [], delta_vs_cheapest_cents: 0, not_ranked: [] },
    one_order: {
      status: 'ranked', reason: null, best_store_id: 'libris',
      answer: { status: 'ranked', reason: null, total_cents: 14462, books_subtotal_cents: 13172, order_count: 1,
        orders: [order('libris', books, 1290, 14462)], delta_vs_cheapest_cents: delta, not_ranked: [] },
      per_book_delta: books.map(([item_id, title, price_cents], i) => ({
        item_id, title, price_cents, cheapest_price_cents: cheapest[i], cheapest_store_id: i < 2 ? 'elefant' : 'libris', delta_cents: perBook[i],
      })),
      shops: [],
    },
    custom: null,
    edition: { pins: {}, unknown_pins: [], status: 'not_possible', reason: null, unpinned_total_cents: null, total_cents: null, delta_cents: null, not_ranked: [] },
    failed_reads: [], memberships: [],
  };
}

function render(perBook: [number, number, number]): HTMLElement {
  spyOn(globalThis, 'fetch').and.resolveTo({ ok: true, json: async () => ({}) } as Response);
  TestBed.inject(BasketService).addUnpriced('9780142500903', 'Jane Eyre', 'Charlotte Bronte');
  const fixture = TestBed.createComponent(AppComponent);
  const app = fixture.componentInstance;
  app.loaded = true;
  app.route = { name: 'result', arg: '' };
  app.data = payload(perBook) as unknown as App['data'];
  app.tab = 'one';
  fixture.detectChanges();
  return fixture.nativeElement as HTMLElement;
}

const text = (el: Element | null) => (el?.textContent || '').replace(/\s+/g, ' ').trim();

describe('one order: where the difference comes from', () => {
  afterEach(() => { localStorage.clear(); window.location.hash = ''; });

  it('adds a "Delivery and fees" row so the rows add up to the heading', () => {
    const el = render([1573, 2901, 0]);
    expect(text(el)).toContain('Where the 17,76 comes from');
    const row = el.querySelector('[data-delivery-delta]');
    expect(text(row)).toContain('Delivery and fees');
    expect(text(row)).toContain('−26,98'); // 15,73 + 29,01 − 26,98 = 17,76
  });

  it('shows no delivery row when the book gaps already make up the difference', () => {
    const el = render([1776, 0, 0]);
    expect(el.querySelector('[data-delivery-delta]')).toBeNull();
  });
});
