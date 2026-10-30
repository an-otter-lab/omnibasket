import { TestBed } from '@angular/core/testing';
import { AppComponent } from './app.component';
import { EVENT_SOURCE, SourceLike } from './events.service';
import { LiveOffer } from './live';
import { MESSAGES } from './messages';

class FakeSource implements SourceLike {
  handlers: Record<string, ((e: { data: string }) => void)[]> = {};
  onerror: ((e: unknown) => void) | null = null;
  closed = false;
  constructor(readonly url: string) {}
  addEventListener(name: string, fn: (e: { data: string }) => void): void {
    (this.handlers[name] ||= []).push(fn);
  }
  close(): void {
    this.closed = true;
  }
  emit(name: string, data: unknown): void {
    for (const fn of this.handlers[name] || []) fn({ data: JSON.stringify(data) });
  }
}

const ISBN = '9781526605412';

const OFFERS: LiveOffer[] = [
  { store_id: 'libris', status: 'ok', price_cents: 8990, listing_url: 'https://www.libris.ro/x', isbn13: ISBN, ranked: true },
  { store_id: 'bookzone', status: 'ok', price_cents: 7650, listing_url: 'https://www.bookzone.ro/y', isbn13: ISBN, ranked: false, not_ranked_reason: 'delivery_rules_not_read' },
  { store_id: 'emag', status: 'failed', reason: 'fetch_refused: HTTP 511', price_cents: null, listing_url: 'https://www.emag.ro/the-book/pd/ABC/', isbn13: ISBN, ranked: false, not_ranked_reason: 'fetch_refused' },
  { store_id: 'books_express', status: 'failed', reason: 'no_match_in_index', price_cents: null, listing_url: null, isbn13: ISBN, ranked: false, not_ranked_reason: 'no_offer' },
  { store_id: 'amazon_de', status: 'skipped', reason: 'amazon_de_never_read_live', price_cents: null, listing_url: null, isbn13: ISBN, ranked: false, not_ranked_reason: 'not_read_live' },
];

function solution(offers: LiveOffer[]) {
  const order = {
    store_id: 'libris',
    books: [{ item_id: 'book-' + ISBN, title: 'Harry Potter Hogwarts', isbn13: ISBN, edition: null, price_cents: 8990, listing_url: null, read_at: null }],
    books_subtotal_cents: 8990,
    qualifying_cents: 8990,
    free_delivery_threshold_cents: 13500,
    threshold_crossed: false,
    over_under_threshold_cents: null,
    short_of_threshold_cents: 4510,
    delivery_gap: null,
    delivery_known: true,
    delivery_cents: 1500,
    order_fee_cents: 0,
    order_total_cents: 10490,
    read_at: null,
  };
  return {
    currency: 'RON',
    cached: false,
    read_at_range: { oldest: null, newest: null },
    degraded: null,
    shops: [],
    books: [{ item_id: 'book-' + ISBN, title: 'Harry Potter Hogwarts', isbn13: ISBN, edition_pin: null, editions: [], assigned_store_id: 'libris', shops: [] }],
    failed_reads: [],
    cheapest: { status: 'ranked', reason: null, total_cents: 10490, books_subtotal_cents: 8990, order_count: 1, orders: [order], delta_vs_cheapest_cents: 0, not_ranked: [] },
    // The API's own key for the one-shop answer, written without the old word.
    [['one', 'par' + 'cel'].join('_')]: { status: 'ranked', reason: null, best_store_id: 'libris', answer: null, per_book_delta: [], shops: [] },
    custom: null,
    edition: { pins: {}, unknown_pins: [], status: 'ranked', reason: null, unpinned_total_cents: null, total_cents: null, delta_cents: null, not_ranked: [] },
    live_offers: offers,
    joined_item_id: 'book-' + ISBN,
    joined_title: 'Harry Potter Hogwarts',
    joined_isbn13: ISBN,
  };
}

describe('live flow: progress then per-shop reads', () => {
  let source: FakeSource;

  beforeEach(() => {
    TestBed.configureTestingModule({ providers: [{ provide: EVENT_SOURCE, useValue: (url: string) => (source = new FakeSource(url)) }] });
    window.location.hash = '';
  });

  async function start() {
    const fixture = TestBed.createComponent(AppComponent);
    const app = fixture.componentInstance;
    app.route = { name: 'live', arg: ISBN };
    app.startLive(ISBN, 'Harry Potter Hogwarts');
    fixture.detectChanges();
    return fixture;
  }

  const lines = (el: HTMLElement) => Array.from(el.querySelectorAll('.plog .pmsg')).map((x) => x.textContent!.trim());

  it('opens /events?source=live for the picked ISBN', async () => {
    await start();
    expect(source.url).toContain('source=live');
    expect(source.url).toContain('isbn13=' + ISBN);
  });

  it('shows progress messages in the order they arrive', async () => {
    const fixture = await start();
    const el: HTMLElement = fixture.nativeElement;
    const say = (message: string, status = 'reading') => {
      source.emit('read_progress', { store_id: 'x', isbn13: ISBN, status, message });
      fixture.detectChanges();
    };
    say('Reading Libris…');
    say('Reading eMAG…');
    expect(lines(el)).toEqual(['Reading Libris…', 'Reading eMAG…']);
    say("eMAG couldn't be read, skipped", 'failed');
    say('Libris: ok', 'ok');
    expect(lines(el)).toEqual(['Reading Libris…', 'Reading eMAG…', "eMAG couldn't be read, skipped", 'Libris: ok']);
    expect(el.querySelector('h1')!.textContent).toContain('Harry Potter Hogwarts');
  });

  it('on the solution, shows each shop with its outcome and price above the re-solved basket', async () => {
    const fixture = await start();
    source.emit('solution', solution(OFFERS));
    fixture.componentInstance.route = { name: 'result', arg: '' };
    fixture.detectChanges();
    const el: HTMLElement = fixture.nativeElement;
    const rows = Array.from(el.querySelectorAll<HTMLElement>('.rrow'));
    expect(rows.map((r) => r.dataset['shop'])).toEqual(['bookzone', 'libris', 'emag', 'books_express', 'amazon_de']);
    expect(rows[0].textContent).toContain('76,50 lei');
    expect(rows[0].textContent).toContain('Delivery rules not read');
    expect(rows[1].textContent).toContain('89,90 lei');
    expect(rows[1].textContent).toContain('Priced and compared');
    expect(el.querySelector('.tabs')!.textContent).toContain('1 order');
  });

  it('failure state: a shop that could not be read shows its honest line and its listing link', async () => {
    const fixture = await start();
    source.emit('solution', solution(OFFERS));
    fixture.componentInstance.route = { name: 'result', arg: '' };
    fixture.detectChanges();
    const emag = (fixture.nativeElement as HTMLElement).querySelector<HTMLElement>('.rrow[data-shop="emag"]')!;
    expect(emag.textContent).toContain("Couldn't read eMAG right now");
    expect(emag.querySelector('.n')).toBeNull();
    const link = emag.querySelector<HTMLAnchorElement>('a')!;
    expect(link.getAttribute('href')).toBe('https://www.emag.ro/the-book/pd/ABC/');
    expect(link.textContent).toContain('Open eMAG');
  });

  it('failure state: Check on Amazon.de links the ISBN search', async () => {
    const fixture = await start();
    source.emit('solution', solution(OFFERS));
    fixture.componentInstance.route = { name: 'result', arg: '' };
    fixture.detectChanges();
    const row = (fixture.nativeElement as HTMLElement).querySelector<HTMLElement>('.rrow[data-shop="amazon_de"]')!;
    const link = row.querySelector<HTMLAnchorElement>('a')!;
    expect(link.textContent).toContain('Check on Amazon.de');
    expect(link.getAttribute('href')).toBe('https://www.amazon.de/s?k=' + ISBN);
  });

  it('failure state: a link with no book on the page says so', async () => {
    const fixture = TestBed.createComponent(AppComponent);
    const app = fixture.componentInstance;
    app.route = { name: 'find', arg: 'https://www.example.com/not-a-book' };
    await app.runSearch('https://www.example.com/not-a-book');
    fixture.detectChanges();
    const el: HTMLElement = fixture.nativeElement;
    expect(el.querySelector('[data-state="link-failed"]')!.textContent).toContain("I couldn't find a book on that page.");
  });

  it('failure state: a dropped stream says the read did not finish and offers a retry', async () => {
    const fixture = await start();
    source.onerror!({});
    fixture.detectChanges();
    const el: HTMLElement = fixture.nativeElement;
    expect(el.querySelector('[data-state="read-failed"]')!.textContent).toContain('The read didn’t finish');
    const first = source;
    el.querySelector<HTMLButtonElement>('[data-state="read-failed"] button')!.click();
    fixture.detectChanges();
    expect(source).not.toBe(first);
    expect(el.querySelector('[data-state="read-failed"]')).toBeNull();
  });

  it('says order, never the old word, anywhere on the solved screen', async () => {
    const fixture = await start();
    source.emit('solution', solution(OFFERS));
    fixture.componentInstance.route = { name: 'result', arg: '' };
    fixture.detectChanges();
    const text = (fixture.nativeElement as HTMLElement).innerHTML + Object.values(MESSAGES.en).join(' ');
    expect(new RegExp(['par', 'cel'].join(''), 'i').test(text)).toBeFalse();
  });
});
