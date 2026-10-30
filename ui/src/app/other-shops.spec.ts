import { TestBed } from '@angular/core/testing';
import { Candidate, LiveOffer } from './live';
import { PickListComponent } from './pick-list.component';
import { ShopReadsComponent } from './shop-reads.component';

const BOOK: Candidate = {
  title: 'Some Book',
  author: null,
  isbn: '9781526605412',
  cover_url: null,
  shops: [],
  other_shops: [
    { shop: 'bookzone', url: 'https://www.bookzone.ro/cautare?q=9781526605412', status: 'not_checked', reason: 'Not checked here' },
    { shop: 'emag', url: 'https://www.emag.ro/search/9781526605412', status: 'not_checked', reason: 'Not checked here' },
  ],
};
const NO_OFFER: LiveOffer = { store_id: 'libris', status: 'no_offer', price_cents: null, listing_url: null, ranked: false, not_ranked_reason: 'no_offer' };

function reads(lang: 'en' | 'ro', pick: Candidate, offers: LiveOffer[]) {
  const f = TestBed.createComponent(ShopReadsComponent);
  Object.assign(f.componentInstance, { lang, pick, offers, isbn: pick.isbn });
  f.detectChanges();
  return f.nativeElement as HTMLElement;
}

describe('other shops (not checked)', () => {
  it('renders reason and link, never "no offer", in the shop view', () => {
    const el = reads('en', BOOK, [{ ...NO_OFFER, store_id: 'books_express' }]);
    const row = el.querySelector('[data-shop="bookzone"]')!;
    expect(row.textContent).toContain('Bookzone');
    expect(row.textContent).toContain('Not checked here');
    expect(row.textContent).not.toContain('No offer');
    expect(row.querySelector('a')!.getAttribute('href')).toContain('bookzone.ro');
    expect(el.querySelector('[data-shop="emag"] a')).toBeTruthy();
  });

  it('does not say no offer for a not-checked shop that has an empty read row', () => {
    const empty = (id: string): LiveOffer => ({ ...NO_OFFER, store_id: id });
    const offers = [empty('books_express'), empty('bookzone'), empty('emag')];
    for (const [lang, line] of [['en', 'Not checked here'], ['ro', 'Nu a fost verificat aici']] as const) {
      const el = reads(lang, BOOK, offers);
      for (const id of ['bookzone', 'emag']) {
        const rows = el.querySelectorAll('[data-shop="' + id + '"]');
        expect(rows.length).toBe(1);
        expect(rows[0].textContent).toContain(line);
        expect(rows[0].textContent).not.toMatch(/No offer|Nicio ofert/);
        expect(rows[0].querySelector('a')).toBeTruthy();
      }
      expect(el.querySelector('[data-shop="books_express"]')!.textContent).toMatch(/No offer|Nicio ofert/);
    }
  });

  it('says it in Romanian', () => {
    const el = reads('ro', BOOK, []);
    expect(el.querySelector('[data-shop="emag"]')!.textContent).toContain('Nu a fost verificat aici');
  });

  it('keeps the no-offer row for a book nobody carries', () => {
    const el = reads('en', { ...BOOK, other_shops: [] }, [NO_OFFER]);
    expect(el.querySelector('[data-outcome="no_offer"]')!.textContent).toContain('No offer found for this ISBN');
    expect(el.querySelector('[data-outcome="not_checked"]')).toBeNull();
  });

  it('shows the honest line and link in the pick row', () => {
    const f = TestBed.createComponent(PickListComponent);
    f.componentInstance.items = [BOOK];
    f.detectChanges();
    // Entry screen v2 folds the not-checked shops into one compact line of chips (name + link, no reason text).
    const chips = Array.from((f.nativeElement as HTMLElement).querySelectorAll('.not-checked .not-checked-chip'));
    const o = chips.find((c) => c.textContent!.includes('Bookzone'))!;
    expect(o).toBeTruthy();
    expect(o.textContent).not.toContain('No offer');
    expect(o.querySelector('a')!.getAttribute('href')).toContain('bookzone.ro');
  });
});
