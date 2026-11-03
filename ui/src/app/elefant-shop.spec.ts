import { LiveOffer, outcomeOf, shopLabel } from './live';
import { BUY_SHOP_NAME, safeListingUrl } from './buy-list';
import { MESSAGES } from './messages';

// Elefant (3 Nov): an indexed shop. A listing sold by another seller on Elefant is listed, not compared.
describe('Elefant shop', () => {
  const row = (over: Partial<LiveOffer>): LiveOffer => ({ store_id: 'elefant', status: 'failed', price_cents: null, listing_url: null, ranked: false, ...over });

  it('is named Elefant everywhere', () => {
    expect(shopLabel('elefant')).toBe('Elefant');
    expect(BUY_SHOP_NAME['elefant']).toBe('Elefant');
  });

  it('links a listing only on its own domain', () => {
    expect(safeListingUrl('elefant', 'https://www.elefant.ro/a-book-paperback_0f0f0f0f-1111-4222-8333-444455556666')).toContain('www.elefant.ro');
    expect(safeListingUrl('elefant', 'https://elefant.example.com/a-book')).toBeNull();
  });

  it('says when the listing is sold by another seller, in EN and RO', () => {
    expect(outcomeOf(row({ not_ranked_reason: 'not_sold_by_shop' }))).toBe('other_seller');
    expect(MESSAGES.en.readsOtherSeller).toContain('{shop}');
    expect(MESSAGES.ro.readsOtherSeller).toContain('{shop}');
    expect(MESSAGES.ro.readsOtherSeller).not.toContain('colet');
  });
});
