import { Candidate, LiveOffer, coverUrl, outcomeOf, parseInput, shopLink, sortOffers, toIsbn13 } from './live';

describe('live helpers', () => {
  it('reads ISBN-13 and ISBN-10 with a valid check digit only', () => {
    expect(toIsbn13('978-1-5266-0541-2')).toBe('9781526605412');
    expect(toIsbn13('0306406152')).toBe('9780306406157');
    expect(toIsbn13('9781526605413')).toBeNull();
    expect(toIsbn13('mackesy')).toBeNull();
  });

  it('classifies the box input', () => {
    expect(parseInput('  ').kind).toBe('empty');
    expect(parseInput('9781526605412')).toEqual({ kind: 'isbn', isbn: '9781526605412' });
    expect(parseInput('the boy the mole').kind).toBe('text');
    expect(parseInput('https://www.books-express.ro/x/p/ap,9781526605412')).toEqual({
      kind: 'link',
      url: 'https://www.books-express.ro/x/p/ap,9781526605412',
      isbn: '9781526605412',
    });
    const none = parseInput('https://www.example.com/some/page');
    expect(none.kind === 'link' && none.isbn).toBeNull();
  });

  it('accepts a cover only from Open Library', () => {
    expect(coverUrl({ cover_url: 'https://covers.openlibrary.org/b/isbn/1-M.jpg', isbn: '1' })).toContain('covers.openlibrary.org');
    expect(coverUrl({ cover_url: 'https://cdn.libris.ro/a.jpg', isbn: '1' })).toBeNull();
    expect(coverUrl({ cover_url: null, isbn: '9781526605412' })).toBeNull();
  });

  const row = (over: Partial<LiveOffer>): LiveOffer => ({ store_id: 'libris', status: 'ok', price_cents: null, listing_url: null, ranked: false, ...over });

  it('maps not_ranked_reason to an outcome', () => {
    expect(outcomeOf(row({ ranked: true, price_cents: 100 }))).toBe('ranked');
    expect(outcomeOf(row({ not_ranked_reason: 'delivery_rules_not_read', price_cents: 100 }))).toBe('not_compared');
    expect(outcomeOf(row({ not_ranked_reason: 'fetch_refused' }))).toBe('refused');
    expect(outcomeOf(row({ not_ranked_reason: 'no_offer' }))).toBe('no_offer');
    expect(outcomeOf(row({ not_ranked_reason: 'no_price_extracted' }))).toBe('no_price');
    expect(outcomeOf(row({ not_ranked_reason: 'not_read_live' }))).toBe('not_live');
  });

  it('links: own listing, then the index listing, never a shop search page', () => {
    const pick: Candidate = { title: 't', author: null, isbn: '9781526605412', cover_url: null, shops: [{ shop: 'books-express', url: 'https://www.books-express.ro/p' }] };
    expect(shopLink(row({ listing_url: 'https://www.libris.ro/a' }), pick)).toBe('https://www.libris.ro/a');
    expect(shopLink(row({ store_id: 'books_express' }), pick)).toBe('https://www.books-express.ro/p');
    // R11: no shop search page is ever linked, and no ISBN search is built for a shop.
    expect(shopLink(row({ store_id: 'emag' }), null)).toBeNull();
    expect(shopLink(row({ store_id: 'amazon_de' }), null)).toBeNull();
    expect(shopLink(row({ store_id: 'bookzone' }), null)).toBeNull();
    expect(shopLink(row({ listing_url: 'javascript:alert(1)' }), null)).toBeNull();
    expect(shopLink(row({ listing_url: ['https://www.emag.ro', 'search', 'x'].join('/') }), null)).toBeNull();
    expect(shopLink(row({ listing_url: 'https://www.bookzone.ro/cautare?q=x' }), null)).toBeNull();
  });

  it('puts priced shops first, cheapest first', () => {
    const rows = [row({ store_id: 'emag' }), row({ store_id: 'libris', price_cents: 900 }), row({ store_id: 'bookzone', price_cents: 700 })];
    expect(sortOffers(rows).map((r) => r.store_id)).toEqual(['bookzone', 'libris', 'emag']);
  });
});
