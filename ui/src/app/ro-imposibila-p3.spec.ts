import { TestBed } from '@angular/core/testing';
import { AppComponent } from './app.component';
import { BasketService } from './basket.service';
import { MESSAGES } from './messages';

// P3 follow-up: the "1 comandă" tab says "imposibilă" (agrees with "comandă"); the
// other uses of "imposibil" and the EN text are unchanged.

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

function noOneOrder(lang: 'en' | 'ro') {
  localStorage.setItem('omnibasket.lang.v1', lang);
  oneBook();
  const r = boot();
  r.app.lang = lang;
  r.app.route = { name: 'result', arg: '' };
  r.app.data = payload(2, null) as unknown as App['data'];
  r.fixture.detectChanges();
  return r;
}

describe('P3: RO "1 comandă / imposibilă"', () => {
  afterEach(() => localStorage.clear());

  it('the RO "1 comandă" tab says "imposibilă"', () => {
    const { el } = noOneOrder('ro');
    const tab = el.querySelector<HTMLElement>('#tab-one')!;
    expect(tab.firstChild!.textContent!.trim()).toBe('1 comandă');
    expect(tab.querySelector('span')!.textContent!.trim()).toBe('imposibilă');
  });

  it('the EN "1 order" tab still says "not possible"', () => {
    const { el } = noOneOrder('en');
    expect(el.querySelector<HTMLElement>('#tab-one span')!.textContent!.trim()).toBe('not possible');
    expect(MESSAGES.en.tabOneNotPossible).toBe(MESSAGES.en.notPossible);
  });

  it('keeps the other RO "imposibil" texts', () => {
    expect(MESSAGES.ro.notPossible).toBe('imposibil');
    expect(MESSAGES.ro.notPossibleTitle).toBe('Imposibil');
    expect(MESSAGES.ro.tabOrdersNotPossible).toBe('imposibile');
  });
});
