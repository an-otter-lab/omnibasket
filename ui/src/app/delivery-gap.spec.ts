import { demoSample } from './demo-sample';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { AppComponent } from './app.component';
import { MESSAGES } from './messages';

// Order rows as /solve returns them for the ro-v1 basket (data/stores/ro.yaml
// thresholds): Libris over its 135 lei bar, Bookzone with Ghici at 46,50 lei
// under its 200 lei bar. The third order is a shop with no known threshold.
function order(store_id: string, extra: Record<string, unknown>) {
  return {
    store_id,
    books: [],
    books_subtotal_cents: 0,
    qualifying_cents: 0,
    free_delivery_threshold_cents: null,
    threshold_crossed: false,
    over_under_threshold_cents: null,
    short_of_threshold_cents: null,
    delivery_gap: null,
    delivery_known: true,
    delivery_cents: 0,
    order_fee_cents: 0,
    order_total_cents: 0,
    read_at: '2026-10-28',
    ...extra,
  };
}

const LIBRIS = order('libris', {
  books_subtotal_cents: 17011,
  qualifying_cents: 17011,
  free_delivery_threshold_cents: 13500,
  threshold_crossed: true,
  over_under_threshold_cents: 3511,
  short_of_threshold_cents: 0,
  delivery_gap: { status: 'reached', short_cents: 0, threshold_cents: 13500 },
  order_total_cents: 17011,
});

const BOOKZONE = order('bookzone', {
  books_subtotal_cents: 4650,
  qualifying_cents: 4650,
  free_delivery_threshold_cents: 20000,
  over_under_threshold_cents: -15350,
  short_of_threshold_cents: 15350,
  delivery_gap: { status: 'short', short_cents: 15350, threshold_cents: 20000 },
  delivery_cents: 1090,
  order_fee_cents: 199,
  order_total_cents: 5939,
});

const UNKNOWN = order('somewhere', { books_subtotal_cents: 1000, qualifying_cents: 1000, order_total_cents: 1000 });

const PAYLOAD = {
  currency: 'RON',
  cached: true,
  read_at_range: { oldest: '2026-10-28', newest: '2026-10-28' },
  degraded: null,
  shops: [],
  books: [],
  failed_reads: [],
  cheapest: {
    status: 'ranked',
    reason: null,
    total_cents: 22950,
    books_subtotal_cents: 22661,
    order_count: 3,
    orders: [LIBRIS, BOOKZONE, UNKNOWN],
    delta_vs_cheapest_cents: 0,
    not_ranked: [],
  },
  one_order: { status: 'ranked', reason: null, best_store_id: null, answer: null, per_book_delta: [], shops: [] },
  custom: null,
  edition: { pins: {}, unknown_pins: [], status: 'ranked', reason: null, unpinned_total_cents: null, total_cents: null, delta_cents: null, not_ranked: [] },
};

async function showResult(lang: 'en' | 'ro') {
  demoSample();
  const fixture: ComponentFixture<AppComponent> = TestBed.createComponent(AppComponent);
  await fixture.componentInstance.load();
  fixture.componentInstance.lang = lang;
  fixture.componentInstance.route = { name: 'result', arg: '' };
  fixture.componentInstance.tab = 'cheapest';
  fixture.detectChanges();
  return fixture;
}

function gapLines(fixture: ComponentFixture<AppComponent>): string[] {
  const el: HTMLElement = fixture.nativeElement;
  return Array.from(el.querySelectorAll('.obox .gap')).map((p) => (p.textContent || '').trim());
}

describe('free-delivery gap per order', () => {
  beforeEach(() => {
    spyOn(window, 'fetch').and.callFake(async () => new Response(JSON.stringify(PAYLOAD), { status: 200 }));
  });

  it('shows the gap in lei with the shop name, and reached, in EN', async () => {
    const fixture = await showResult('en');
    expect(gapLines(fixture)).toEqual(['Free delivery reached', '153,50 lei short of free delivery at Bookzone']);
  });

  it('shows the same lines in RO with comma decimals', async () => {
    const fixture = await showResult('ro');
    expect(gapLines(fixture)).toEqual([
      'Comanda are livrare gratuită',
      'Mai ai 153,50 lei până la livrarea gratuită la Bookzone',
    ]);
  });

  it('hides the line entirely when the threshold is unknown', async () => {
    const fixture = await showResult('en');
    const cards = Array.from((fixture.nativeElement as HTMLElement).querySelectorAll('.obox'));
    const unknown = cards.find((c) => (c.textContent || '').includes('somewhere'));
    expect(unknown).toBeTruthy();
    expect(unknown!.querySelector('.gap')).toBeNull();
    expect(unknown!.textContent).not.toContain('free delivery');
    expect(fixture.componentInstance.deliveryGap(UNKNOWN as never)).toBe('');
    // A recorded payload without the field also hides it.
    const { delivery_gap: _drop, ...older } = UNKNOWN;
    expect(fixture.componentInstance.deliveryGap(older as never)).toBe('');
  });

  it('keeps RO copy on comma-below ș/ț and never says the old word', () => {
    const all = Object.values(MESSAGES).flatMap((m) => Object.values(m)).join(' ');
    expect(/[\u015E\u015F\u0162\u0163]/.test(all)).toBeFalse();
    // Entry screen v2 explicitly uses "parcel"/"colet" in headline and step 3 per design spec
    const entryV2Keys = ['entryHeadline', 'entryStep3'];
    const otherMessages = Object.values(MESSAGES)
      .flatMap((m) => Object.entries(m))
      .filter(([key]) => !entryV2Keys.includes(key))
      .map(([_, value]) => value)
      .join(' ');
    expect(new RegExp(['par', 'cel|colet'].join(''), 'i').test(otherMessages)).toBeFalse();
    expect(Object.keys(MESSAGES.ro).sort()).toEqual(Object.keys(MESSAGES.en).sort());
  });
});
