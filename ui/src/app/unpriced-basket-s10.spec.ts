import { TestBed } from '@angular/core/testing';
import { AppComponent } from './app.component';
import { BasketService } from './basket.service';
import { EVENT_SOURCE, SourceLike } from './events.service';
import { LiveOffer } from './live';
import { MESSAGES } from './messages';

// S10: a basket where no book can be priced has a heading and an Add a book button, not just the shop rows.

const A = '9780142402535';
const B = '9786060339229';
const SHOP = {
  store_id: 'libris', priced: true, excluded: false, selectable: true, not_selectable_code: null, not_selectable_reason: null,
  read_at: '2026-10-31T10:00:00Z', books_listed: 0, failed_reads: [], free_delivery_threshold_cents: 15000,
  delivery_cents: 1500, delivery_known: true, order_fee_cents: 0, currency: 'RON',
};

function unpriced(isbn: string, title: string) {
  const id = 'book-' + isbn;
  const offers: LiveOffer[] = ['libris', 'emag'].map((store_id) => (
    { store_id, status: 'failed', reason: 'no_match_in_index', price_cents: null, listing_url: null, isbn13: isbn, ranked: false, not_ranked_reason: 'no_offer' }));
  return {
    currency: 'RON', shops: [SHOP], failed_reads: [],
    books: [{ item_id: id, title, isbn13: isbn, edition_pin: null, editions: [], assigned_store_id: null, shops: [] }],
    live_offers: offers, joined_item_id: id, joined_title: title, joined_isbn13: isbn,
  };
}

class FakeSource implements SourceLike {
  onerror: ((e: unknown) => void) | null = null;
  constructor(readonly url: string) {}
  addEventListener(): void {}
  close(): void {}
}

describe('S10: a basket where no book can be priced', () => {
  let solves = 0;

  beforeEach(() => {
    localStorage.clear();
    window.location.hash = '';
    solves = 0;
    spyOn(window, 'fetch').and.callFake(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith('/solve')) solves++;
      return { ok: url.endsWith('/config'), status: url.endsWith('/config') ? 200 : 404, json: async () => ({ demo: false }) } as Response;
    });
    TestBed.configureTestingModule({ providers: [{ provide: EVENT_SOURCE, useValue: (url: string) => new FakeSource(url) }] });
  });
  afterEach(() => { localStorage.clear(); window.location.hash = ''; });

  async function open(books: [string, string][], lang = 'en') {
    localStorage.setItem('omnibasket.lang.v1', lang);
    const svc = TestBed.inject(BasketService);
    for (const [isbn, title] of books) svc.addFromLive(unpriced(isbn, title), isbn, title);
    window.location.hash = '#/result/cheapest';
    const fixture = TestBed.createComponent(AppComponent);
    fixture.componentInstance.route = { name: 'result', arg: '' };
    fixture.detectChanges();
    for (let n = 0; n < 4; n++) { await fixture.whenStable(); await new Promise((r) => setTimeout(r, 0)); fixture.detectChanges(); }
    return fixture.nativeElement as HTMLElement;
  }

  it('says none of the books could be priced and offers Add a book; the shop rows stay', async () => {
    const el = await open([[A, 'Matilda'], [B, 'Micul prinț']]);
    const screen = el.querySelector('[data-screen="none-priced"]')!;
    expect(screen).not.toBeNull();
    expect(screen.querySelector('h1')!.textContent!.trim()).toBe(MESSAGES.en.nonePricedTitle);
    const add = screen.querySelector<HTMLAnchorElement>('[data-action="unpriced-add"]')!;
    expect(add.getAttribute('href')).toBe('#/add');
    expect(add.textContent!.trim()).toBe(MESSAGES.en.basketAddBook);
    expect(el.querySelectorAll('[data-section="your-books"] .ybook').length).toBe(2);
    expect(solves).toBe(0);
  });

  it('one book: the heading is about that book', async () => {
    const el = await open([[A, 'Matilda']]);
    expect(el.querySelector('[data-screen="none-priced"] h1')!.textContent!.trim()).toBe(MESSAGES.en.nonePricedOne);
  });

  it('RO: heading and button in Romanian', async () => {
    const el = await open([[A, 'Matilda'], [B, 'Micul prinț']], 'ro');
    expect(el.querySelector('[data-screen="none-priced"] h1')!.textContent!.trim()).toBe(MESSAGES.ro.nonePricedTitle);
    expect(el.querySelector('[data-action="unpriced-add"]')!.textContent!.trim()).toBe(MESSAGES.ro.basketAddBook);
  });

  // #29 follow-up: "book" or "books" by count, in both languages, comma-below ș/ț in RO.
  it('RO one book: the singular heading (carte), and the plural says cărți', async () => {
    const el = await open([[A, 'Matilda']], 'ro');
    const h = el.querySelector('[data-screen="none-priced"] h1')!.textContent!.trim();
    expect(h).toBe(MESSAGES.ro.nonePricedOne);
    expect(h).toContain('această carte');
    expect(MESSAGES.ro.nonePricedTitle).toContain('aceste cărți');
    for (const t of [MESSAGES.ro.nonePricedOne, MESSAGES.ro.nonePricedTitle]) expect(t).not.toMatch(/[şţŞŢ]/);
    expect(MESSAGES.en.nonePricedOne).toMatch(/\bbook\b/);
    expect(MESSAGES.en.nonePricedTitle).toMatch(/\bbooks\b/);
  });
});
