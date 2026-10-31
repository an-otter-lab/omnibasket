import { TestBed } from '@angular/core/testing';
import { By } from '@angular/platform-browser';
import { demoSample } from './demo-sample';
import { AppComponent } from './app.component';
import { AskBoxComponent } from './ask-box.component';
import { MEMBERSHIPS_KEY, MembershipRow } from './memberships';

// R10: the result's dead controls. A membership for a shop with no book in the basket is
// hidden; the editions control exists only when a book has a second edition; a locked
// custom switch says which book it is the only shop for.

const GENIUS: MembershipRow = {
  id: 'emag_genius', store_id: 'emag', store_name: 'eMAG', name: 'eMAG Genius',
  effect: 'unknown', read_status: 'refused', declared: false, changes_totals: false,
  source_url: 'https://www.emag.ro/genius', read_date: '2026-10-30', evidence: 'captcha',
  member_threshold_cents: null, store_threshold_cents: null, store_currency: null, everyone_rule: null,
};
const PRIME: MembershipRow = {
  ...GENIUS, id: 'amazon_prime', store_id: 'amazon_de', store_name: 'Amazon.de', name: 'Amazon Prime',
  effect: 'none', read_status: 'read', source_url: 'https://www.amazon.de/prime',
};

interface ShopIn {
  store_id: string;
  selectable?: boolean;
  books_listed?: number;
}

function shop(s: ShopIn) {
  return {
    store_id: s.store_id, currency: 'RON', priced: true, excluded: false,
    selectable: s.selectable !== false, not_selectable_code: null, not_selectable_reason: null,
    read_at: null, books_listed: s.books_listed ?? 1, failed_reads: [],
    free_delivery_threshold_cents: 13500, delivery_cents: 1290, delivery_known: true, order_fee_cents: 0,
  };
}

const ORDER = {
  store_id: 'libris',
  books: [{ item_id: 'a', title: 'Harry Potter', isbn13: '9781526605412', edition: null, price_cents: 5000, seller_certainty: 'direct', listing_url: 'https://www.libris.ro/x', read_at: null }],
  books_subtotal_cents: 5000, qualifying_cents: 5000, free_delivery_threshold_cents: 13500,
  threshold_crossed: false, over_under_threshold_cents: -8500, short_of_threshold_cents: 8500,
  delivery_known: true, delivery_cents: 1290, order_fee_cents: 0, order_total_cents: 6290, read_at: null,
};

function payload(opts: { editions: boolean; shops: ShopIn[] }) {
  const book = {
    item_id: 'a', title: 'Harry Potter', isbn13: '9781526605412', edition_pin: null,
    editions: opts.editions
      ? [{ edition: 'paperback', cheapest_price_cents: 5000, store_ids: ['libris'] }, { edition: 'hardcover', cheapest_price_cents: 7000, store_ids: ['libris'] }]
      : [],
    assigned_store_id: 'libris',
    shops: [{ store_id: 'libris', status: 'in_plan', price_cents: 5000, seller_certainty: 'direct', edition: null }],
  };
  return {
    currency: 'RON', cached: true, read_at_range: { oldest: '2026-10-30', newest: '2026-10-30' },
    degraded: null,
    shops: opts.shops.map(shop),
    books: [book],
    failed_reads: [],
    memberships: [GENIUS, PRIME],
    cheapest: { status: 'ranked', reason: null, total_cents: 6290, books_subtotal_cents: 5000, order_count: 1, orders: [ORDER], delta_vs_cheapest_cents: 0, not_ranked: [] },
    ['one_' + 'parcel']: { status: 'not_possible', reason: null, best_store_id: null, answer: null, per_book_delta: [], shops: [] },
    custom: { status: 'ranked', reason: null, total_cents: 6290, books_subtotal_cents: 5000, order_count: 1, orders: [ORDER], delta_vs_cheapest_cents: 0, not_ranked: [], selected_store_ids: ['libris'], unselectable: [], moves: [] },
    edition: { pins: {}, unknown_pins: [], status: 'ranked', reason: null, unpinned_total_cents: null, total_cents: null, delta_cents: null, not_ranked: [] },
  };
}

async function render(opts: { editions: boolean; shops: ShopIn[]; ask?: unknown[]; solves?: Record<string, unknown>[] }) {
  demoSample();
  const body = payload(opts);
  spyOn(window, 'fetch').and.callFake(async (url: RequestInfo | URL, init?: RequestInit) => {
    const u = String(url);
    if (u.endsWith('/why')) return new Response(JSON.stringify({ text: 'Sentence.', source: 'template' }), { status: 200 });
    if (u.endsWith('/ask')) {
      return new Response(JSON.stringify({ status: 'ok', actions: opts.ask ?? [], reply_key: 'askDoneMembership', reply_args: { name: 'eMAG Genius' } }), { status: 200 });
    }
    if (u.endsWith('/solve')) (opts.solves ?? []).push(JSON.parse(String(init?.body || '{}')) as Record<string, unknown>);
    return new Response(JSON.stringify(body), { status: 200 });
  });
  const fixture = TestBed.createComponent(AppComponent);
  await fixture.componentInstance.load();
  fixture.componentInstance.route = { name: 'result', arg: '' };
  fixture.componentInstance.tab = 'cheapest';
  fixture.detectChanges();
  await fixture.whenStable();
  return fixture;
}

describe('result dead controls (R10)', () => {
  it('hides the editions control when no book has a second edition', async () => {
    const el = (await render({ editions: false, shops: [{ store_id: 'libris' }] })).nativeElement as HTMLElement;
    expect(el.querySelector('[data-editions-row]')).toBeNull();
  });

  it('shows the editions control when a book has a second edition', async () => {
    const el = (await render({ editions: true, shops: [{ store_id: 'libris' }] })).nativeElement as HTMLElement;
    expect(el.querySelector('[data-editions-row]')).not.toBeNull();
    expect(el.querySelector('[data-editions-row] a')!.getAttribute('href')).toBe('#/editions');
  });

  it('shows a membership only for a shop that can take a book', async () => {
    const none = (await render({ editions: false, shops: [{ store_id: 'libris' }] })).nativeElement as HTMLElement;
    expect(none.querySelectorAll('app-memberships [data-membership]').length).toBe(0);
    const emag = (await render({ editions: false, shops: [{ store_id: 'libris' }, { store_id: 'emag' }] })).nativeElement as HTMLElement;
    const rows = emag.querySelectorAll('app-memberships [data-membership]');
    expect(rows.length).toBe(1);
    expect(rows[0].getAttribute('data-membership')).toBe('emag_genius');
  });

  it('says why the last chosen shop cannot be switched off', async () => {
    const fixture = await render({ editions: false, shops: [{ store_id: 'libris' }] });
    const app = fixture.componentInstance;
    app.tab = 'custom';
    fixture.detectChanges();
    const reason = app.lockedReason((app.data!.shops[0] as never));
    expect(reason).toBe('Only shop with Harry Potter');
    const desc = (fixture.nativeElement as HTMLElement).querySelector('[data-shop-switch="libris"] input')!.getAttribute('aria-describedby');
    expect(desc).toContain('libris');
  });

  it('offers the membership ask chip only when that shop can take a book, and the chip acts', async () => {
    localStorage.removeItem(MEMBERSHIPS_KEY);
    const none = (await render({ editions: false, shops: [{ store_id: 'libris' }] })).nativeElement as HTMLElement;
    const noneChips = Array.from(none.querySelectorAll('app-ask-box .ask-chips .chip')).map((c) => c.textContent!.trim());
    expect(noneChips.length).toBeGreaterThan(0);
    expect(noneChips.some((t) => t.includes('Genius'))).toBeFalse();

    const solves: Record<string, unknown>[] = [];
    const fixture = await render({ editions: false, shops: [{ store_id: 'libris' }, { store_id: 'emag' }], ask: [{ name: 'set_membership', args: { membership_id: 'emag_genius', on: true } }], solves });
    const el = fixture.nativeElement as HTMLElement;
    const chip = Array.from(el.querySelectorAll<HTMLButtonElement>('app-ask-box .ask-chips .chip')).find((c) => c.textContent!.includes('Genius'));
    expect(chip).not.toBeUndefined();
    expect(chip!.textContent!.trim()).toBe('I have eMAG Genius');

    chip!.click();
    const box = fixture.debugElement.query(By.directive(AskBoxComponent)).componentInstance as AskBoxComponent;
    for (let i = 0; i < 200 && (box.working || box.busy || fixture.componentInstance.busy); i++) { await new Promise((r) => setTimeout(r, 10)); fixture.detectChanges(); }
    expect(solves.some((s) => Array.isArray(s['memberships']) && (s['memberships'] as string[]).includes('emag_genius'))).toBeTrue();
    expect(fixture.componentInstance.declaredMemberships).toContain('emag_genius');
    expect(el.querySelector<HTMLInputElement>('app-memberships [data-membership="emag_genius"] input')!.checked).toBeTrue();
  });
});
