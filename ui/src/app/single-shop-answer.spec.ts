import { TestBed } from '@angular/core/testing';
import { AppComponent } from './app.component';
import { BasketService } from './basket.service';
import { MESSAGES } from './messages';

// Adrian, 3 Nov: when only one shop can be priced and it has every book, its one order is the
// cheapest answer (Matilda + Gruffalo at Libris, 126,51 lei), not "No ranked answer".
// "Only one shop could be priced" stays as a note.

type App = AppComponent;

const LIBRIS = {
  store_id: 'libris', books: [], books_subtotal_cents: 11361, qualifying_cents: 11361, free_delivery_threshold_cents: 20000,
  threshold_crossed: false, over_under_threshold_cents: null, short_of_threshold_cents: 8639, delivery_known: true,
  delivery_cents: 1290, order_fee_cents: 0, order_total_cents: 12651, read_at: null,
};

function payload(cheapestRanked: boolean) {
  const answer = { status: 'ranked', total_cents: 12651, order_count: 1, delta_vs_cheapest_cents: 0, orders: [LIBRIS], not_ranked: [], reason: null };
  const refusal = { status: 'not_possible', total_cents: null, order_count: null, delta_vs_cheapest_cents: null, orders: [], not_ranked: [],
    reason: 'only one shop can be priced for these books', reason_code: 'one_shop', reason_args: {}, degraded: true };
  return {
    currency: 'RON', cached: false, read_at_range: { oldest: null, newest: null },
    degraded: { kind: 'one_shop', store_id: 'libris', reason: 'only one shop can be priced for these books', reason_code: 'one_shop', reason_args: {} },
    shops: [], books: [],
    cheapest: cheapestRanked ? answer : refusal,
    one_order: { status: 'ranked', reason: null, best_store_id: 'libris', answer, per_book_delta: [], shops: [] },
    custom: null,
    edition: { pins: {}, unknown_pins: [], status: 'ranked', reason: null, unpinned_total_cents: null, total_cents: null, delta_cents: null, not_ranked: [] },
    failed_reads: [], memberships: [],
  };
}

function boot(lang: 'en' | 'ro', cheapestRanked = true) {
  localStorage.setItem('omnibasket.lang.v1', lang);
  TestBed.inject(BasketService).addUnpriced('9780142402535', 'Matilda', 'Roald Dahl');
  spyOn(globalThis, 'fetch').and.resolveTo({ ok: true, json: async () => ({}) } as Response);
  const fixture = TestBed.createComponent(AppComponent);
  const app = fixture.componentInstance;
  app.loaded = true;
  app.lang = lang;
  app.route = { name: 'result', arg: '' };
  app.tab = 'cheapest';
  app.data = payload(cheapestRanked) as unknown as App['data'];
  fixture.detectChanges();
  return { app, el: fixture.nativeElement as HTMLElement };
}

describe('One shop priced: its one order is the cheapest answer', () => {
  afterEach(() => localStorage.clear());

  it('the cheapest tab shows the shop\'s total with the note, not "No ranked answer", EN', () => {
    const { app, el } = boot('en');
    const text = el.textContent!;
    expect(text).toContain('126,51 lei');
    expect(text).toContain('Only Libris could be priced for these books · delivery included');
    expect(text).not.toContain(MESSAGES.en.noRanked);
    expect(app.activeTabId).toBe('tab-cheapest');
    expect(el.querySelector('#tab-cheapest')!.textContent).toContain('Libris only');
  });

  it('the same in Romanian', () => {
    const { el } = boot('ro');
    const text = el.textContent!;
    expect(text).toContain('126,51 lei');
    expect(text).toContain('Doar Libris a putut fi calculat pentru aceste cărți · livrare inclusă');
    expect(text).not.toContain(MESSAGES.ro.noRanked);
  });

  const oneShopOnly = (a: App) => (a as unknown as { oneShopOnly: (d: unknown) => boolean }).oneShopOnly(a.data);
  it('stays on the cheapest tab when the one shop has a ranked order', () => {
    expect(oneShopOnly(boot('en').app)).toBeFalse();
  });
  it('a one shop with no ranked order still sends the page to the one-order tab', () => {
    expect(oneShopOnly(boot('en', false).app)).toBeTrue();
  });

  it('the one-order tab gives the "only one shop" reason from the note', () => {
    const { app } = boot('en');
    expect(app.why(app.data!.degraded)).toBe(MESSAGES.en.rsOneShop);
    app.lang = 'ro';
    expect(app.why(app.data!.degraded)).toBe(MESSAGES.ro.rsOneShop);
  });
});
