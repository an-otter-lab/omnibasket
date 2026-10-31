import { LiveOffer, listingUrl, shopLink } from './live';

describe('S5: Amazon.de search pages are never a link', () => {
  const row = (over: Partial<LiveOffer>): LiveOffer => ({ store_id: 'amazon_de', status: 'skipped', price_cents: null, listing_url: null, ranked: false, ...over });

  it('rejects the Amazon search URL', () => {
    expect(listingUrl('https://www.amazon.de/s?k=9780747532699')).toBeNull();
    expect(listingUrl('https://www.amazon.de/s?k=978-0-7475-3269-9&ref=nb')).toBeNull();
  });

  it('keeps a captured Amazon product page', () => {
    expect(listingUrl('https://www.amazon.de/dp/1529105102')).toBe('https://www.amazon.de/dp/1529105102');
    expect(listingUrl('https://www.amazon.de/Some-Book/dp/1529105102')).toBe('https://www.amazon.de/Some-Book/dp/1529105102');
  });

  it('a new book on Amazon.de has no link', () => {
    expect(shopLink(row({ listing_url: 'https://www.amazon.de/s?k=9780747532699' }), null)).toBeNull();
    expect(shopLink(row({}), null)).toBeNull();
  });
});
