// Types and pure helpers for the one-box flow: ISBN reading, Open Library
// covers, shop names and the per-shop read outcomes carried by live_offers[].

export interface Candidate {
  title: string;
  author: string | null;
  isbn: string | null;
  cover_url: string | null;
  shops: { shop: string; url: string }[];
}

export interface Progress {
  store_id: string;
  isbn13: string | null;
  status: string;
  message: string;
}

export interface LiveOffer {
  store_id: string;
  status: string;
  reason?: string | null;
  price_cents: number | null;
  listing_url: string | null;
  isbn13?: string | null;
  ranked: boolean;
  not_ranked_reason?: string;
}

export type Outcome = 'ranked' | 'not_compared' | 'refused' | 'no_offer' | 'no_price' | 'not_live' | 'other';

export const SHOP_LABEL: Record<string, string> = {
  libris: 'Libris',
  emag: 'eMAG',
  bookzone: 'Bookzone',
  amazon_de: 'Amazon.de',
  carturesti: 'Cărturești',
  books_express: 'Books-Express',
  'books-express': 'Books-Express',
};

export function shopLabel(id: string | null | undefined): string {
  return id ? SHOP_LABEL[id] || id : '';
}

const OPEN_LIBRARY = 'https://covers.openlibrary.org/';

/** An Open Library cover URL, or null. A shop image is never used as a cover. */
export function coverUrl(c: { cover_url: string | null; isbn: string | null }): string | null {
  const given = c.cover_url;
  if (given && given.startsWith(OPEN_LIBRARY)) return given + (given.includes('?') ? '' : '?default=false');
  return null;
}

function checkDigit13(d: string): boolean {
  let sum = 0;
  for (let i = 0; i < 12; i++) sum += Number(d[i]) * (i % 2 === 0 ? 1 : 3);
  return (10 - (sum % 10)) % 10 === Number(d[12]);
}

function isbn10to13(d: string): string | null {
  let sum = 0;
  for (let i = 0; i < 9; i++) {
    if (!/\d/.test(d[i])) return null;
    sum += (10 - i) * Number(d[i]);
  }
  const last = d[9].toUpperCase();
  sum += last === 'X' ? 10 : Number(last);
  if (Number.isNaN(sum) || sum % 11 !== 0) return null;
  const body = '978' + d.slice(0, 9);
  let s = 0;
  for (let i = 0; i < 12; i++) s += Number(body[i]) * (i % 2 === 0 ? 1 : 3);
  return body + String((10 - (s % 10)) % 10);
}

/** A valid ISBN-13 (ISBN-10 is converted), or null. */
export function toIsbn13(text: string): string | null {
  const t = text.replace(/[\s-]/g, '');
  if (/^\d{13}$/.test(t)) return checkDigit13(t) ? t : null;
  if (/^\d{9}[\dXx]$/.test(t)) return isbn10to13(t);
  return null;
}

export type Parsed =
  | { kind: 'empty' }
  | { kind: 'isbn'; isbn: string }
  | { kind: 'text'; text: string }
  | { kind: 'link'; url: string; isbn: string | null };

/**
 * What the box was given. A link is not fetched here: the only thing read from it
 * is a valid ISBN printed in the address. No ISBN means "no book found".
 */
export function parseInput(raw: string): Parsed {
  const text = raw.trim();
  if (!text) return { kind: 'empty' };
  if (/^https?:\/\//i.test(text)) {
    for (const m of text.match(/97[89][\d-]{10,14}|\b\d{9}[\dXx]\b/g) || []) {
      const isbn = toIsbn13(m);
      if (isbn) return { kind: 'link', url: text, isbn };
    }
    return { kind: 'link', url: text, isbn: null };
  }
  const isbn = toIsbn13(text);
  if (isbn) return { kind: 'isbn', isbn };
  return { kind: 'text', text };
}

export function outcomeOf(o: LiveOffer): Outcome {
  if (o.ranked) return 'ranked';
  switch (o.not_ranked_reason) {
    case 'delivery_rules_not_read':
      return o.price_cents != null ? 'not_compared' : 'other';
    case 'fetch_refused':
      return 'refused';
    case 'no_offer':
      return 'no_offer';
    case 'no_price_extracted':
      return 'no_price';
    case 'not_read_live':
      return 'not_live';
    default:
      return 'other';
  }
}

/**
 * The link a shopper can follow for a shop. The listing the read used first,
 * then the listing the index holds for the picked book, then (only for eMAG and
 * Amazon.de) a search for the ISBN. Null where none is known.
 */
export function shopLink(o: LiveOffer, pick: Candidate | null, isbn: string | null): string | null {
  const ok = (u: string | null | undefined) => (u && /^https?:\/\//.test(u) ? u : null);
  const own = ok(o.listing_url);
  if (own) return own;
  const key = o.store_id.replace(/_/g, '-');
  const indexed = pick?.shops.find((s) => s.shop.replace(/_/g, '-') === key);
  const fromIndex = ok(indexed?.url);
  if (fromIndex) return fromIndex;
  const code = isbn || o.isbn13 || pick?.isbn || null;
  if (!code) return null;
  if (o.store_id === 'amazon_de') return 'https://www.amazon.de/s?k=' + code;
  if (o.store_id === 'emag') return 'https://www.emag.ro/search/' + code;
  return null;
}

/** Priced shops first, cheapest first; the rest keep the order the backend gave. */
export function sortOffers(rows: LiveOffer[]): LiveOffer[] {
  const priced = rows.filter((r) => r.price_cents != null).sort((a, b) => (a.price_cents as number) - (b.price_cents as number));
  return [...priced, ...rows.filter((r) => r.price_cents == null)];
}
