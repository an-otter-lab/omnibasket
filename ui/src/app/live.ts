// Types and pure helpers for the one-box flow: ISBN reading, Open Library
// covers, shop names and the per-shop read outcomes carried by live_offers[].

export interface Candidate {
  title: string;
  author: string | null;
  isbn: string | null;
  cover_url: string | null;
  shops: { shop: string; url: string }[];
  /** Shops that are not indexed: a link and an honest reason, never a price. */
  other_shops?: { shop: string; url: string; status: string; reason: string }[];
}

/** Up to two capitals from the title, for the cover placeholder. */
export function initials(title: string): string {
  const words = (title || '').split(/\s+/).filter((w) => /^\p{L}/u.test(w) && w.length > 2);
  return words.slice(0, 2).map((w) => w[0].toUpperCase()).join('') || '·';
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
  /** The shop's page declares another ISBN of the same work. */
  other_printing?: boolean;
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
  // S4b: an ISBN-13 always starts 978 or 979; anything else is a product barcode.
  if (/^\d{13}$/.test(t)) return /^97[89]/.test(t) && checkDigit13(t) ? t : null;
  if (/^\d{9}[\dXx]$/.test(t)) return isbn10to13(t);
  return null;
}

export type Parsed =
  | { kind: 'empty' }
  | { kind: 'isbn'; isbn: string }
  | { kind: 'text'; text: string }
  | { kind: 'link'; url: string; isbn: string | null };

export interface PastedBook {
  isbn: string;
  title: string | null;
  author: string | null;
  /** The pasted page itself: the shop's own listing is read for its price. */
  listing: string | null;
}

/**
 * The book a pasted shop link resolved to. POST /input read the page, so a link
 * with no ISBN in its address still names a book (R3). Null when nothing resolved.
 */
export function pastedBook(body: unknown): PastedBook | null {
  if (!body || typeof body !== 'object') return null;
  const b = body as {
    status?: string;
    isbn13?: string | null;
    structured_query?: { title?: string | null; author?: string | null } | null;
    shop_context?: { shop_id?: string | null; product_url?: string | null } | null;
    candidates?: { title?: string | null; author?: string | null; isbn13?: string | null }[] | null;
  };
  if (b.status !== 'resolved') return null;
  const listing = b.shop_context?.shop_id && b.shop_context?.product_url ? b.shop_context.product_url : null;
  const isbn = b.isbn13 ? toIsbn13(String(b.isbn13)) : null;
  if (isbn) {
    return { isbn, title: b.structured_query?.title ?? null, author: b.structured_query?.author ?? null, listing };
  }
  for (const c of b.candidates || []) {
    const picked = c && c.isbn13 ? toIsbn13(String(c.isbn13)) : null;
    if (picked) return { isbn: picked, title: c.title ?? null, author: c.author ?? null, listing };
  }
  return null;
}

/**
 * What the box was given. A link is not fetched here: the only thing read from it
 * is a valid ISBN printed in the address. With no ISBN the caller asks POST /input.
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
 * R11: the only links a shopper follows go to a shop's listing page. A shop search page
 * (`/search`, `/cautare?q=`, Amazon's `/s?k=`) or any URL carrying a query is never a link.
 */
export function listingUrl(u: string | null | undefined): string | null {
  if (!u || !/^https?:\/\//i.test(u)) return null;
  if (/\/(search|cautare)([/?]|$)/i.test(u) || /[?&]q=/i.test(u)) return null;
  if (/\/s\?/i.test(u)) return null; // S5: Amazon's search page (/s?k=…)
  return u;
}

/**
 * The link a shopper can follow for a shop: the listing the read used, then the listing the
 * index holds for the picked book. Null where no listing page is known (R11: no search links).
 */
export function shopLink(o: LiveOffer, pick: Candidate | null): string | null {
  const own = listingUrl(o.listing_url);
  if (own) return own;
  const key = o.store_id.replace(/_/g, '-');
  const indexed = pick?.shops.find((s) => s.shop.replace(/_/g, '-') === key);
  return listingUrl(indexed?.url);
}

/** Priced shops first, cheapest first; the rest keep the order the backend gave. */
export function sortOffers(rows: LiveOffer[]): LiveOffer[] {
  const priced = rows.filter((r) => r.price_cents != null).sort((a, b) => (a.price_cents as number) - (b.price_cents as number));
  return [...priced, ...rows.filter((r) => r.price_cents == null)];
}

/**
 * S8: a 10- or 13-digit entry (hyphens and spaces allowed) that fails the check digit. It is a
 * mistyped ISBN, not a title: the shopper is told so and the text stays in the field.
 */
export function badIsbn(raw: string): boolean {
  const t = raw.trim().replace(/[\s-]/g, '');
  return (/^\d{13}$/.test(t) || /^\d{9}[\dXx]$/.test(t)) && toIsbn13(t) === null;
}
