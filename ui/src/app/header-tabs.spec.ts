import { TestBed } from '@angular/core/testing';
import { AppComponent } from './app.component';
import { BasketService } from './basket.service';

// R5 + R7: one header on every screen, with the basket count and no old pill bars;
// and one "1 order · cheapest" tab (plus Custom) when the cheapest split is a single order.

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

function header(el: HTMLElement): HTMLElement {
  const all = el.querySelectorAll<HTMLElement>('header.hdr');
  expect(all.length).toBe(1);
  return all[0];
}

function pillText(el: HTMLElement): string {
  const pill = el.querySelector<HTMLElement>('[data-header-count]');
  expect(pill).not.toBeNull();
  return pill!.textContent!.replace(/\s+/g, ' ').trim();
}

describe('one header everywhere (R5)', () => {
  beforeEach(() => {
    localStorage.clear();
    window.location.hash = '';
  });

  afterEach(() => {
    localStorage.clear();
    window.location.hash = '';
  });

  it('keeps the old EN/RO and System/Light/Dark pill bars off every screen', () => {
    oneBook();
    const { app, el, fixture } = boot();
    for (const name of ['find', 'result', 'basket', 'buy'] as const) {
      app.route = name === 'basket' ? { name: 'result', arg: '' } : { name, arg: name === 'find' ? 'Sapiens' : '' };
      app.data = name === 'basket' ? null : (payload(2, 900) as unknown as App['data']);
      fixture.detectChanges();
      expect(el.querySelector('.prefs')).toBeNull();
      expect(el.querySelector('.seg')).toBeNull();
      expect(el.querySelector('button[data-theme-option]')).toBeNull();
      expect(el.querySelectorAll('[aria-pressed="true"]').length).toBe(0);
      expect(header(el)).not.toBeNull();
    }
  });

  it('shows the same header with the basket count on find, result, basket and buy', () => {
    oneBook();
    const { app, el, fixture } = boot();

    app.route = { name: 'find', arg: 'Sapiens' };
    fixture.detectChanges();
    expect(header(el).textContent).toContain('omnibasket');
    expect(pillText(el)).toContain('1 book');
    expect(pillText(el)).toContain('See orders');
    expect(el.querySelector('#lang-btn')).not.toBeNull();
    expect(el.querySelector('#theme-btn')).not.toBeNull();

    app.route = { name: 'result', arg: '' };
    app.data = payload(2, 900) as unknown as App['data'];
    fixture.detectChanges();
    expect(pillText(el)).toContain('1 book');
    expect(pillText(el)).not.toContain('See orders');
    expect(el.querySelector('#lang-btn')).not.toBeNull();

    app.route = { name: 'result', arg: '' };
    app.data = null;
    fixture.detectChanges();
    expect(el.querySelector('[data-section="your-books"]')).not.toBeNull();
    expect(pillText(el)).toContain('1 book');
    expect(el.querySelector('#lang-btn')).not.toBeNull();

    app.route = { name: 'buy', arg: 'not-a-code' };
    fixture.detectChanges();
    expect(pillText(el)).toContain('1 book');
    expect(pillText(el)).toContain('See orders');
    expect(el.querySelector('#theme-btn')).not.toBeNull();
  });

  it('hides the count when the basket is empty', () => {
    const { app, el, fixture } = boot();
    app.route = { name: 'result', arg: '' };
    fixture.detectChanges();
    expect(el.querySelector('[data-header-count]')).toBeNull();
    expect(header(el).textContent).toContain('omnibasket');
  });
});

describe('one tab when the cheapest split is one order (R7)', () => {
  beforeEach(() => {
    localStorage.clear();
    window.location.hash = '';
  });

  afterEach(() => {
    localStorage.clear();
    window.location.hash = '';
  });

  function tabTexts(el: HTMLElement): string[] {
    return [...el.querySelectorAll<HTMLElement>('.tabs a, .tabs .off')].map((a) => a.textContent!.replace(/\s+/g, ' ').trim().toLowerCase());
  }

  it('reads "1 order · cheapest" and Custom, with no duplicate 1 order tab', () => {
    oneBook();
    const { app, el, fixture } = boot();
    app.route = { name: 'result', arg: '' };
    app.data = payload(1, null) as unknown as App['data'];
    fixture.detectChanges();

    const tabs = tabTexts(el);
    expect(tabs.length).toBe(2);
    expect(tabs[0]).toContain('1 order');
    expect(tabs[0]).toContain('cheapest');
    expect(tabs[1]).toContain('custom');
    expect(el.querySelectorAll('.tabs > *').length).toBe(2);
  });

  it('keeps three tabs when the split is several orders and one order costs more', () => {
    oneBook();
    const { app, el, fixture } = boot();
    app.route = { name: 'result', arg: '' };
    app.data = payload(2, 1250) as unknown as App['data'];
    fixture.detectChanges();

    const tabs = tabTexts(el);
    expect(tabs.length).toBe(3);
    expect(tabs[0]).toContain('1 order');
    expect(tabs[1]).toContain('cheapest');
    expect(tabs[1]).toContain('2 orders');
    expect(tabs[2]).toContain('custom');
  });
});
