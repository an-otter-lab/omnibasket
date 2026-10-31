import { TestBed, fakeAsync, tick } from '@angular/core/testing';
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

  it('is the same bar on the photo, live, loading and failed-load screens', () => {
    oneBook();
    const { app, el, fixture } = boot();
    for (const name of ['photo', 'live'] as const) {
      app.route = { name, arg: '' };
      app.data = null;
      fixture.detectChanges();
      expect(header(el)).not.toBeNull();
      expect(pillText(el)).toContain('1 book');
      expect(el.querySelector('#lang-btn')).not.toBeNull();
      expect(el.querySelector('#theme-btn')).not.toBeNull();
    }
    app.route = { name: 'result', arg: '' };
    app.loading = true;
    fixture.detectChanges();
    expect(pillText(el)).toContain('1 book');
    app.loading = false;
    app.loadError = true;
    fixture.detectChanges();
    expect(pillText(el)).toContain('1 book');
    expect(el.querySelector('#lang-btn')).not.toBeNull();
  });

  it('opens the language and theme menus as listboxes that mark the current choice', () => {
    oneBook();
    const { app, el, fixture } = boot();
    app.route = { name: 'find', arg: 'Sapiens' };
    fixture.detectChanges();

    const langButton = el.querySelector<HTMLElement>('#lang-btn')!;
    expect(langButton.getAttribute('aria-haspopup')).toBe('listbox');
    expect(langButton.getAttribute('aria-expanded')).toBe('false');
    const langMenu = el.querySelector<HTMLElement>('#lang-menu')!;
    expect(langMenu.getAttribute('role')).toBe('listbox');
    expect(langMenu.getAttribute('aria-hidden')).toBe('true');

    langButton.click();
    fixture.detectChanges();
    expect(langButton.getAttribute('aria-expanded')).toBe('true');
    expect(langMenu.getAttribute('aria-hidden')).toBe('false');
    expect(el.querySelector('#lang-opt-en')!.getAttribute('aria-checked')).toBe('true');
    expect(el.querySelector('#lang-opt-ro')!.getAttribute('aria-checked')).toBe('false');

    const themeMenu = el.querySelector<HTMLElement>('#theme-menu')!;
    el.querySelector<HTMLElement>('#theme-btn')!.click();
    fixture.detectChanges();
    expect(themeMenu.getAttribute('role')).toBe('listbox');
    expect(el.querySelector('#theme-opt-system')!.getAttribute('aria-checked')).toBe('true');
    expect(langMenu.getAttribute('aria-hidden')).toBe('true');
  });

  it('closes a menu on Escape and puts focus back on its trigger', fakeAsync(() => {
    oneBook();
    const { app, el, fixture } = boot();
    app.route = { name: 'find', arg: 'Sapiens' };
    fixture.detectChanges();
    const langButton = el.querySelector<HTMLElement>('#lang-btn')!;
    langButton.click();
    fixture.detectChanges();
    tick();
    const menu = el.querySelector<HTMLElement>('#lang-menu')!;
    expect(document.activeElement!.id).toBe('lang-opt-en');
    menu.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    fixture.detectChanges();
    tick();
    expect(menu.getAttribute('aria-hidden')).toBe('true');
    expect(document.activeElement!.id).toBe('lang-btn');
  }));
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

  it('never writes "1 order +0,00": a one-order basket at the cheapest price says so', () => {
    oneBook();
    const { app, el, fixture } = boot();
    app.route = { name: 'result', arg: '' };
    app.data = payload(2, 0) as unknown as App['data'];
    fixture.detectChanges();

    const first = el.querySelector<HTMLElement>('#tab-one')!;
    expect(first.textContent).not.toContain('+0');
    expect(first.textContent!.toLowerCase()).toContain('same as the cheapest');
  });

  it('marks the tabs as a tablist whose selected tab names the panel', () => {
    oneBook();
    const { app, el, fixture } = boot();
    app.route = { name: 'result', arg: '' };
    app.data = payload(1, null) as unknown as App['data'];
    fixture.detectChanges();

    const list = el.querySelector<HTMLElement>('.tabs')!;
    expect(list.getAttribute('role')).toBe('tablist');
    const tabs = [...list.querySelectorAll<HTMLElement>('[role="tab"]')];
    expect(tabs.map((t) => t.id)).toEqual(['tab-cheapest', 'tab-custom']);
    expect(tabs[0].getAttribute('aria-selected')).toBe('true');
    expect(tabs[0].getAttribute('tabindex')).toBe('0');
    expect(tabs[1].getAttribute('aria-selected')).toBe('false');
    expect(tabs[1].getAttribute('tabindex')).toBe('-1');
    const panel = el.querySelector<HTMLElement>('main[role="tabpanel"]')!;
    expect(panel.getAttribute('aria-labelledby')).toBe('tab-cheapest');
  });

  it('moves between tabs with the arrow keys and activates the next one', () => {
    oneBook();
    const { app, el, fixture } = boot();
    app.route = { name: 'result', arg: '' };
    app.data = payload(2, 1250) as unknown as App['data'];
    fixture.detectChanges();

    const list = el.querySelector<HTMLElement>('.tabs')!;
    const one = el.querySelector<HTMLElement>('#tab-one')!;
    const cheapest = el.querySelector<HTMLElement>('#tab-cheapest')!;
    const custom = el.querySelector<HTMLElement>('#tab-custom')!;
    const clicked: string[] = [];
    for (const [id, tab] of [['one', one], ['cheapest', cheapest], ['custom', custom]] as const) {
      tab.addEventListener('click', (event) => {
        event.preventDefault();
        clicked.push(id);
      });
    }

    cheapest.focus();
    list.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }));
    expect(clicked).toEqual(['custom']);

    custom.focus();
    list.dispatchEvent(new KeyboardEvent('keydown', { key: 'Home', bubbles: true }));
    expect(clicked).toEqual(['custom', 'one']);

    list.dispatchEvent(new KeyboardEvent('keydown', { key: 'End', bubbles: true }));
    expect(clicked).toEqual(['custom', 'one', 'custom']);
  });

  it('gives a disabled tab no place in the arrow order', () => {
    oneBook();
    const { app, el, fixture } = boot();
    app.route = { name: 'result', arg: '' };
    app.data = { ...(payload(2, 1250) as Record<string, unknown>), degraded: { kind: 'one_shop', store_id: 'libris' } } as unknown as App['data'];
    fixture.detectChanges();

    const list = el.querySelector<HTMLElement>('.tabs')!;
    const tabs = [...list.querySelectorAll<HTMLElement>('[role="tab"]')];
    expect(tabs.length).toBe(3);
    expect(tabs[1].getAttribute('aria-disabled')).toBe('true');
    const one = el.querySelector<HTMLElement>('#tab-one')!;
    let clicks = 0;
    one.addEventListener('click', (event) => {
      event.preventDefault();
      clicks++;
    });
    one.focus();
    list.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }));
    // the only enabled tab is the first one, so the arrow wraps back to it
    expect(clicks).toBe(1);
  });
});
