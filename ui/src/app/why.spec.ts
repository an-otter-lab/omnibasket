import { ComponentFixture, TestBed } from '@angular/core/testing';
import { AppComponent } from './app.component';
import { MESSAGES, Messages } from './messages';
import { demoSample } from './demo-sample';

const DESCRIBABLE = {
  books: [{ item_id: 'x' }],
  cheapest: { orders: [{ store_id: 's' }] },
};

const TEMPLATE_EN = 'The cheapest split is 462,58\u00a0lei in 2 orders, from Books-Express and Libris.';
const TEMPLATE_RO = 'Cea mai ieftină împărțire este 462,58\u00a0lei în 2 comenzi, de la Books-Express și Libris.';

const order = (store: string) => ({
  store_id: store,
  books: [{ item_id: 'b1', title: 'b1', isbn13: null, edition: 'paperback', price_cents: 1000, listing_url: null, read_at: null }],
  books_subtotal_cents: 1000, qualifying_cents: 1000, free_delivery_threshold_cents: null, threshold_crossed: false,
  over_under_threshold_cents: null, short_of_threshold_cents: null, delivery_known: true, delivery_cents: 0, order_fee_cents: 0, order_total_cents: 1000, read_at: null,
});
const ans = (orders: ReturnType<typeof order>[]) => ({ status: 'ranked', reason: null, total_cents: 2000, books_subtotal_cents: 2000, order_count: orders.length, orders, delta_vs_cheapest_cents: 0, not_ranked: [] });

function payload() {
  const o = [order('libris'), order('books_express')];
  return {
    currency: 'RON', cached: true, read_at_range: { oldest: null, newest: null }, degraded: null,
    shops: ['libris', 'books_express'].map((s) => ({ store_id: s, priced: true, excluded: false, selectable: true, not_selectable_code: null, not_selectable_reason: null, read_at: null, books_listed: 1, failed_reads: [], free_delivery_threshold_cents: null, delivery_cents: 0, delivery_known: true, order_fee_cents: 0 })),
    books: ['b1', 'b2'].map((id) => ({ item_id: id, title: id, isbn13: null, edition_pin: null, editions: [{ edition: 'paperback', cheapest_price_cents: 1000, store_ids: ['libris'] }], assigned_store_id: 'libris', shops: [] })),
    failed_reads: [],
    memberships: [],
    cheapest: ans(o),
    ['one_' + 'par' + 'cel']: { status: 'ranked', reason: null, best_store_id: 'libris', answer: ans([order('libris')]), per_book_delta: [], shops: [] },
    custom: null,
    edition: { pins: {}, unknown_pins: [], status: 'ranked', reason: null, unpinned_total_cents: null, total_cents: null, delta_cents: null, not_ranked: [] },
  };
}

describe('split explanation', () => {
  let component: AppComponent;
  let fixture: ComponentFixture<AppComponent>;
  let fetchSpy: jasmine.Spy;
  let whyReply: () => Promise<Response>;

  beforeEach(async () => {
    whyReply = async () => ({ ok: true, json: async () => ({ text: 'Muse paragraph.', source: 'muse' }) } as Response);
    fetchSpy = spyOn(globalThis, 'fetch').and.callFake(async (input: URL | RequestInfo) => {
      const url = typeof input === 'string' ? input : input.toString();
      if (url === '/why') return whyReply();
      if (url.endsWith('/solve')) return { ok: true, json: async () => payload() } as Response;
      return { ok: true, json: async () => ({}) } as Response;
    });
    demoSample();
    fixture = TestBed.createComponent(AppComponent);
    component = fixture.componentInstance;
    await component.load();
    await fixture.whenStable();
    fixture.detectChanges();
    fetchSpy.calls.reset();
  });

  afterEach(() => { window.location.hash = ''; });

  function request(body: unknown = DESCRIBABLE) {
    return (component as unknown as { loadWhy: (p: unknown) => Promise<void> }).loadWhy(body);
  }

  const boxText = () => fixture.nativeElement.querySelector('[data-why-text]')?.textContent?.trim() ?? null;

  it('starts with no sentence while the request is in flight, then shows the Muse paragraph', async () => {
    const pending = request(DESCRIBABLE);
    expect(component.whyText).toBe('');
    expect(component.whyLoading).toBeTrue();
    await pending;
    expect(component.whyText).toBe('Muse paragraph.');
    expect(component.whyMuse).toBeTrue();
    expect(component.whyLoading).toBeFalse();
  });

  it('shows the server template sentence when /why answers source:template', async () => {
    whyReply = async () => ({ ok: true, json: async () => ({ text: TEMPLATE_EN, source: 'template' }) } as Response);
    await request(DESCRIBABLE);
    fixture.detectChanges();
    expect(component.whyText).toBe(TEMPLATE_EN);
    expect(component.whyMuse).toBeFalse();
    expect(boxText()).toBe(TEMPLATE_EN);
    expect(fixture.nativeElement.querySelector('.why-label')!.textContent).toBe(MESSAGES.en.whyTitle);
  });

  it('hides the whole box when /why fails', async () => {
    whyReply = async () => { throw new Error('offline'); };
    await request(DESCRIBABLE);
    fixture.detectChanges();
    expect(component.whyText).toBe('');
    expect(component.whyLoading).toBeFalse();
    expect(fixture.nativeElement.querySelector('[data-why]')).toBeNull();
    expect(component.note).toBe('');
  });

  it('hides the box on an HTTP error and on an empty or unknown answer', async () => {
    for (const reply of [
      async () => ({ ok: false, json: async () => ({}) } as Response),
      async () => ({ ok: true, json: async () => ({ text: '   ', source: 'template' }) } as Response),
      async () => ({ ok: true, json: async () => ({ text: 'x', source: 'guess' }) } as Response),
    ]) {
      whyReply = reply;
      await request(DESCRIBABLE);
      fixture.detectChanges();
      expect(component.whyText).toBe('');
      expect(fixture.nativeElement.querySelector('[data-why]')).toBeNull();
    }
  });

  it('hides the box instead of fetching when the payload has no books or no orders', async () => {
    await request({});
    expect(fetchSpy).not.toHaveBeenCalled();
    expect(component.whyText).toBe('');
    expect(component.whyLoading).toBeFalse();
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('[data-why]')).toBeNull();
  });

  it('clears the old language answer at once and asks again in the new one', async () => {
    await request(DESCRIBABLE);
    expect(component.whyText).toBe('Muse paragraph.');
    let resolveRo!: (r: Response) => void;
    whyReply = () => new Promise<Response>((resolve) => { resolveRo = resolve; });
    component.lang = 'ro';
    fixture.detectChanges();
    await fixture.whenStable();
    expect(component.whyText).toBe('');
    expect(component.whyLoading).toBeTrue();
    const sent = fetchSpy.calls.allArgs().map((a) => JSON.parse(String((a[1] as RequestInit).body)));
    expect(sent[sent.length - 1].lang).toBe('ro');
    resolveRo({ ok: true, json: async () => ({ text: TEMPLATE_RO, source: 'template' }) } as Response);
    await new Promise((r) => setTimeout(r, 0));
    await fixture.whenStable();
    expect(component.whyText).toBe(TEMPLATE_RO);
  });

  it('ignores an older response after a newer request', async () => {
    let resolveOld!: (response: Response) => void;
    whyReply = () => new Promise<Response>((resolve) => { resolveOld = resolve; });
    const old = request(DESCRIBABLE);
    whyReply = async () => ({ ok: true, json: async () => ({ text: 'new', source: 'muse' }) } as Response);
    await request(DESCRIBABLE);
    resolveOld({ ok: true, json: async () => ({ text: 'old', source: 'muse' }) } as Response);
    await old;
    expect(component.whyText).toBe('new');
  });

  it('carries no circular placeholder sentence in either language', () => {
    const text = (lang: 'en' | 'ro') => JSON.stringify(MESSAGES[lang] as unknown as Record<string, unknown>);
    expect((MESSAGES.en as unknown as Record<string, unknown>)['whySplitTemplate']).toBeUndefined();
    expect((MESSAGES.ro as unknown as Record<string, unknown>)['whySplitTemplate']).toBeUndefined();
    expect(text('en')).not.toContain('explains this basket');
    expect(text('ro')).not.toContain('explică cel mai mic total');
    const copy = MESSAGES.en as unknown as Messages;
    expect(copy.whyTitle).toBe('Why this split');
    expect(MESSAGES.ro.whyTitle).toBe('De ce această împărțire');
  });
});
