import { TestBed } from '@angular/core/testing';
import { AppComponent } from './app.component';
import { BasketService } from './basket.service';
import { MESSAGES } from './messages';

// P3: RO copy. The disabled "orders" tab says "imposibile" (plural, like "comenzi"); the
// "1 comandă" tab says "imposibilă" (its own key since the follow-up). The entry placeholder is a real Romanian edition title.

type App = AppComponent;

function payload(orderCount: number, oneOrderDelta: number | null) {
  const answer = {
    status: 'ranked',
    total_cents: 4200,
    order_count: orderCount,
    delta_vs_cheapest_cents: 0,
    orders: [],
    not_ranked: [],
    reason: null,
  };
  return {
    currency: 'RON',
    cached: false,
    read_at_range: { oldest: null, newest: null },
    degraded: null,
    shops: [],
    books: [],
    cheapest: { ...answer, total_cents: 4200 },
    one_order: {
      status: 'ranked',
      reason: null,
      best_store_id: 'libris',
      answer: oneOrderDelta == null ? null : { ...answer, order_count: 1, delta_vs_cheapest_cents: oneOrderDelta, orders: [] },
      per_book_delta: [],
      shops: [],
    },
    custom: null,
    edition: { pins: {}, unknown_pins: [], status: 'not_possible', reason: null, unpinned_total_cents: null, total_cents: null, delta_cents: null, not_ranked: [] },
    failed_reads: [],
    memberships: [],
  };
}

function boot(): { app: App; el: HTMLElement; fixture: ReturnType<typeof TestBed.createComponent<AppComponent>> } {
  spyOn(globalThis, 'fetch').and.resolveTo({ ok: true, json: async () => ({}) } as Response);
  const fixture = TestBed.createComponent(AppComponent);
  const app = fixture.componentInstance;
  app.loaded = true;
  return { app, el: fixture.nativeElement as HTMLElement, fixture };
}

function oneBook(): void {
  TestBed.inject(BasketService).addUnpriced('9781526605412', 'Book A', 'Author A');
}


function oneShop(lang: 'en' | 'ro') {
  localStorage.setItem('omnibasket.lang.v1', lang);
  oneBook();
  const r = boot();
  r.app.lang = lang;
  r.app.route = { name: 'result', arg: '' };
  r.app.data = { ...(payload(2, 1250) as Record<string, unknown>), degraded: { kind: 'one_shop', store_id: 'libris' } } as unknown as App['data'];
  r.fixture.detectChanges();
  return r;
}

describe('P3: RO copy', () => {
  afterEach(() => localStorage.clear());

  it('the disabled orders tab says "comenzi / imposibile" in Romanian', () => {
    const { el } = oneShop('ro');
    const tab = el.querySelector<HTMLElement>('#tab-orders')!;
    expect(tab.firstChild!.textContent!.trim()).toBe('comenzi');
    expect(tab.querySelector('span')!.textContent!.trim()).toBe('imposibile');
  });

  it('keeps "orders / not possible" in English', () => {
    const { el } = oneShop('en');
    expect(el.querySelector<HTMLElement>('#tab-orders span')!.textContent!.trim()).toBe('not possible');
  });

  it('the "1 comandă" tab says "imposibilă" (follow-up)', () => {
    expect(MESSAGES.ro.tabOneNotPossible).toBe('imposibilă');
    oneBook();
    const { app, el, fixture } = boot();
    app.lang = 'ro';
    app.route = { name: 'result', arg: '' };
    app.data = payload(2, null) as unknown as App['data'];
    fixture.detectChanges();
    expect(el.querySelector<HTMLElement>('#tab-one span')!.textContent!.trim()).toBe('imposibilă');
  });

  it('the RO entry placeholder is the Romanian edition of Room on the Broom', () => {
    expect(MESSAGES.ro.entryPlaceholder).toBe('ex. Loc la voi pe măturoi');
    expect(MESSAGES.en.entryPlaceholder).toBe('e.g. Room on the Broom');
  });
});
