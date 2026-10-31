import { TestBed } from '@angular/core/testing';
import { demoSample } from './demo-sample';
import { AppComponent } from './app.component';
import { MEMBERSHIPS_KEY, MembershipRow } from './memberships';

// S6 (R10): Options renders only when it has something in it (a second edition or a membership).
// The two rows /solve returns for ro-v1 (data/shops/*.yaml, Spike 3, read 30 Oct 2026).
const PRIME: MembershipRow = {
  id: 'amazon_prime',
  store_id: 'amazon_de',
  store_name: 'Amazon.de',
  name: 'Amazon Prime',
  effect: 'none',
  read_status: 'read',
  declared: false,
  changes_totals: false,
  source_url: 'https://www.amazon.de/gp/help/customer/display.html?nodeId=GZXW7X6AKTHNUP6H',
  read_date: '2026-10-30',
  evidence: 'Romania block: Standardzustellung, Mindestbestellwert 49 €',
  member_threshold_cents: null,
  store_threshold_cents: 26217,
  store_currency: 'RON',
  everyone_rule: {
    amount_cents: 4900,
    currency: 'EUR',
    source_url: 'https://www.amazon.de/gp/help/customer/display.html?nodeId=GZXW7X6AKTHNUP6H',
    read_date: '2026-10-28',
  },
};
const GENIUS: MembershipRow = {
  id: 'emag_genius',
  store_id: 'emag',
  store_name: 'eMAG',
  name: 'eMAG Genius',
  effect: 'unknown',
  read_status: 'refused',
  declared: false,
  changes_totals: false,
  source_url: 'https://www.emag.ro/genius',
  read_date: '2026-10-30',
  evidence: 'HTTP 511, eMAG Captcha',
  member_threshold_cents: null,
  store_threshold_cents: null,
  store_currency: null,
  everyone_rule: null,
};
const ROWS = [PRIME, GENIUS];

describe('S6: the Options panel is never empty', () => {
  afterEach(() => localStorage.removeItem(MEMBERSHIPS_KEY));

  async function result(rows: MembershipRow[], editions = false): Promise<HTMLElement> {
    localStorage.removeItem(MEMBERSHIPS_KEY);
    const payload = {
      currency: 'RON',
      cached: true,
      read_at_range: { oldest: '2026-10-28', newest: '2026-10-28' },
      degraded: null,
      shops: [
        { store_id: 'emag', priced: true, excluded: false, selectable: true, not_selectable_code: null, not_selectable_reason: null, read_at: null, books_listed: 1, failed_reads: [], free_delivery_threshold_cents: null, delivery_cents: null, delivery_known: false, order_fee_cents: null },
        { store_id: 'amazon_de', priced: true, excluded: false, selectable: true, not_selectable_code: null, not_selectable_reason: null, read_at: null, books_listed: 1, failed_reads: [], free_delivery_threshold_cents: null, delivery_cents: null, delivery_known: false, order_fee_cents: null },
      ],
      books: [],
      failed_reads: [],
      memberships: rows,
      cheapest: { status: 'ranked', reason: null, total_cents: 51516, books_subtotal_cents: 0, order_count: 2, orders: [], delta_vs_cheapest_cents: 0, not_ranked: [] },
      ['one_' + 'par' + 'cel']: { status: 'ranked', reason: null, best_store_id: null, answer: null, per_book_delta: [], shops: [] },
      custom: null,
      edition: { pins: {}, unknown_pins: [], status: 'ranked', reason: null, unpinned_total_cents: null, total_cents: null, delta_cents: null, not_ranked: [] },
    };
    spyOn(window, 'fetch').and.callFake(async (url: RequestInfo | URL) => {
      if (String(url).endsWith('/why')) {
        return new Response(JSON.stringify({ text: 'Fallback explanation.', source: 'template' }), { status: 200 });
      }
      return new Response(JSON.stringify(payload), { status: 200 });
    });
    demoSample();
    const fixture = TestBed.createComponent(AppComponent);
    if (editions) spyOnProperty(fixture.componentInstance, 'hasEditions', 'get').and.returnValue(true);
    await fixture.componentInstance.load();
    fixture.componentInstance.route = { name: 'result', arg: '' };
    fixture.componentInstance.tab = 'cheapest';
    fixture.detectChanges();
    return fixture.nativeElement as HTMLElement;
  }

  it('no second edition and no membership: no Options at all', async () => {
    const el = await result([]);
    expect(el.querySelector('[data-options]')).toBeNull();
    expect(el.querySelector('app-memberships')).toBeNull();
  });

  it('a membership to offer: Options is there with the membership rows', async () => {
    const el = await result(ROWS);
    expect(el.querySelector('[data-options]')).not.toBeNull();
    expect(el.querySelector('[data-options] [data-membership="amazon_prime"]')).not.toBeNull();
  });

  it('a second edition and no membership: Options is there with the editions row', async () => {
    const el = await result([], true);
    expect(el.querySelector('[data-options]')).not.toBeNull();
    expect(el.querySelector('[data-options] [data-editions-row]')).not.toBeNull();
  });
});
