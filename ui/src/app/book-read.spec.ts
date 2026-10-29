import { ComponentFixture, TestBed } from '@angular/core/testing';
import { AppComponent } from './app.component';

function offer(store_id: string, extra: Record<string, unknown>) {
  return {
    store_id,
    status: 'compared',
    price_cents: null,
    currency: 'RON',
    seller_certainty: null,
    edition: 'board_book',
    listing_url: null,
    read_at: '2026-10-29',
    ...extra,
  };
}

const PAYLOAD = {
  currency: 'RON',
  source: 'cache',
  cached: true,
  read_at_range: { oldest: '2026-10-28', newest: '2026-10-29' },
  degraded: null,
  total_cents: 51516,
  shop_count: 1,
  shops: [{ store_id: 'bookzone', priced: true, free_delivery_threshold_cents: 20000, read_at: '2026-10-29', selectable: true }],
  pages: [],
  failed_reads: [],
  books: [
    {
      item_id: 'ghici',
      title: 'Ghici cât de mult te iubesc',
      isbn13: '9786068996011',
      edition_pin: null,
      editions: [{ edition: 'board_book', cheapest_price_cents: 4650, store_ids: ['bookzone'] }],
      assigned_store_id: 'bookzone',
      shops: [
        offer('bookzone', {
          status: 'in_plan',
          price_cents: 4650,
          seller_certainty: 'direct',
          model_read: { status: 'match', model: 'muse-spark-1.3', read_at: '2026-10-29T19:01:11+02:00', mismatch_fields: [] },
        }),
        offer('libris', {
          price_cents: 5700,
          seller_certainty: 'direct',
          model_read: {
            status: 'mismatch',
            model: 'muse-spark-1.3',
            read_at: '2026-10-29T19:01:27+02:00',
            mismatch_fields: ['price'],
          },
        }),
        offer('emag', {
          status: 'couldnt_read',
          model_read: { status: 'not_read', model: null, read_at: null, mismatch_fields: [] },
        }),
      ],
    },
  ],
  cheapest: { status: 'ranked', total_cents: 51516, order_count: 1, orders: [] },
  one_parcel: { status: 'ranked', best_store_id: 'bookzone', answer: { total_cents: 51516, orders: [] } },
  custom: null,
  edition: { pins: {}, unknown_pins: [], status: 'ranked', reason: null, unpinned_total_cents: 51516, total_cents: 51516, delta_cents: 0, not_ranked: [] },
  assignment: [],
  stores: [],
  membership: [],
  excluded_stores: [],
};

async function showBook(status: Record<string, unknown>) {
  const fixture: ComponentFixture<AppComponent> = TestBed.createComponent(AppComponent);
  await fixture.componentInstance.load();
  fixture.componentInstance.route = { name: 'book', arg: 'ghici' };
  fixture.detectChanges();
  return fixture;
}

describe('book detail read line', () => {
  beforeEach(() => {
    // Each call needs a fresh Response: a body can only be read once.
    spyOn(window, 'fetch').and.callFake(
      async () => new Response(JSON.stringify(PAYLOAD), { status: 200 })
    );
  });

  it('says a matching offer was read by Muse Spark', async () => {
    const fixture = await showBook({});
    const text = fixture.nativeElement.textContent as string;
    expect(text).toContain('Read by Muse Spark · matches the page');
  });

  it('shows an orange tag naming the field when the read disagrees, and keeps the price', async () => {
    const fixture = await showBook({});
    const element: HTMLElement = fixture.nativeElement;
    const tag = element.querySelector('.tagbad');
    expect(tag).not.toBeNull();
    expect(tag!.textContent).toContain('doesn’t match the page · price');
    expect(element.textContent).toContain('57,00');
  });

  it('shows nothing for an offer the model did not read', async () => {
    const fixture = await showBook({});
    const element: HTMLElement = fixture.nativeElement;
    const emagRow = Array.from(element.querySelectorAll('.row')).find((row) =>
      (row.textContent || '').includes('eMAG')
    );
    expect(emagRow).toBeTruthy();
    expect(emagRow!.querySelector('.tagbad')).toBeNull();
    expect(emagRow!.textContent).not.toContain('Read by Muse Spark');
  });
});
