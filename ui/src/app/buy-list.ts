// Feature 6: the buy list travels inside its own link (#/buy/<code>), so a
// shared link restores it with no server storage. The code is base64url of a
// compact JSON array. Everything in it comes from the /solve orders.

export interface BuyBook {
  title: string;
  price_cents: number | null;
  listing_url: string | null;
}

/** S28: the order's delivery, fee and total from the result. Null: not printed by the shop / no total. */
export interface BuyCosts {
  delivery_cents: number | null;
  fee_cents: number | null;
  total_cents: number | null;
}

export interface BuyShop {
  store_id: string;
  books: BuyBook[];
  /** Absent in links written before S28: the list then shows book prices only. */
  costs?: BuyCosts;
}

/** The fields of a /solve order the buy list reads. */
export interface OrderLike {
  store_id: string;
  books: { title: string; price_cents: number; listing_url: string | null }[];
  delivery_known?: boolean;
  delivery_cents?: number | null;
  order_fee_cents?: number | null;
  order_total_cents?: number | null;
}

const VERSION = 1;
const MAX_CODE = 20000;
const MAX_SHOPS = 20;
const MAX_BOOKS = 100;

// Same names as AppComponent's SHOP_NAME, plus Books-Express (data/shops).
export const BUY_SHOP_NAME: Record<string, string> = {
  libris: 'Libris',
  emag: 'eMAG',
  bookzone: 'Bookzone',
  amazon_de: 'Amazon.de',
  books_express: 'Books-Express',
  carturesti: 'Cărturești',
};

// A listing link for an indexed shop is shown only on that shop's own domain
// (data/shops/*.yaml). A crafted share link cannot point "Libris" elsewhere.
const SHOP_HOSTS: Record<string, string[]> = {
  libris: ['www.libris.ro', 'libris.ro'],
  bookzone: ['bookzone.ro', 'www.bookzone.ro'],
  emag: ['www.emag.ro', 'emag.ro'],
  amazon_de: ['www.amazon.de', 'amazon.de'],
  books_express: ['www.books-express.ro', 'books-express.ro'],
};

export function buyListFromOrders(orders: OrderLike[]): BuyShop[] {
  return orders.map((o) => {
    const shop: BuyShop = {
      store_id: o.store_id,
      books: o.books.map((b) => ({ title: b.title, price_cents: b.price_cents, listing_url: b.listing_url ?? null })),
    };
    // S28: a /solve order always says whether its delivery is known; carry delivery, fee and total.
    if (o.delivery_known !== undefined) {
      shop.costs = {
        delivery_cents: o.delivery_known ? (o.delivery_cents ?? null) : null,
        fee_cents: o.order_fee_cents ?? null,
        total_cents: o.order_total_cents ?? null,
      };
    }
    return shop;
  });
}

function toBase64Url(text: string): string {
  const bytes = new TextEncoder().encode(text);
  let bin = '';
  bytes.forEach((b) => (bin += String.fromCharCode(b)));
  return btoa(bin).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

function fromBase64Url(code: string): string {
  const b64 = code.replace(/-/g, '+').replace(/_/g, '/');
  const bin = atob(b64 + '='.repeat((4 - (b64.length % 4)) % 4));
  const bytes = Uint8Array.from(bin, (c) => c.charCodeAt(0));
  return new TextDecoder('utf-8', { fatal: true }).decode(bytes);
}

export function encodeBuyList(shops: BuyShop[]): string {
  // S28: the costs ride after the books ([id, books, delivery, fee, total]); older readers ignore them.
  const compact = [
    VERSION,
    shops.map((s) => {
      const row: unknown[] = [s.store_id, s.books.map((b) => [b.title, b.price_cents, b.listing_url])];
      if (s.costs) row.push(s.costs.delivery_cents, s.costs.fee_cents, s.costs.total_cents);
      return row;
    }),
  ];
  return toBase64Url(JSON.stringify(compact));
}

/** Null when the code is not a buy list this version wrote. */
export function decodeBuyList(code: string): BuyShop[] | null {
  if (!code || code.length > MAX_CODE || !/^[A-Za-z0-9_-]+$/.test(code)) return null;
  let raw: unknown;
  try {
    raw = JSON.parse(fromBase64Url(code));
  } catch {
    return null;
  }
  if (!Array.isArray(raw) || raw[0] !== VERSION || !Array.isArray(raw[1]) || raw[1].length > MAX_SHOPS) return null;
  const shops: BuyShop[] = [];
  for (const s of raw[1] as unknown[]) {
    if (!Array.isArray(s) || typeof s[0] !== 'string' || !/^[a-z0-9_-]{1,40}$/.test(s[0])) return null;
    if (!Array.isArray(s[1]) || s[1].length > MAX_BOOKS) return null;
    const books: BuyBook[] = [];
    for (const b of s[1] as unknown[]) {
      if (!Array.isArray(b) || typeof b[0] !== 'string' || b[0].length > 300) return null;
      const price = b[1];
      if (price !== null && !(Number.isInteger(price) && (price as number) >= 0)) return null;
      const url = b[2];
      if (url !== null && (typeof url !== 'string' || url.length > 2000)) return null;
      books.push({ title: b[0], price_cents: price as number | null, listing_url: url as string | null });
    }
    const shop: BuyShop = { store_id: s[0], books };
    if (s.length > 2) {
      const [delivery, fee, total] = [s[2], s[3], s[4]].map((v) => (v === undefined ? null : v));
      if (![delivery, fee, total].every((v) => v === null || (Number.isInteger(v) && (v as number) >= 0))) return null;
      shop.costs = { delivery_cents: delivery as number | null, fee_cents: fee as number | null, total_cents: total as number | null };
    }
    shops.push(shop);
  }
  return shops;
}

/** The listing URL if it is http(s) and, for an indexed shop, on that shop's domain. */
export function safeListingUrl(storeId: string, url: string | null): string | null {
  if (!url) return null;
  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    return null;
  }
  if (parsed.protocol !== 'https:' && parsed.protocol !== 'http:') return null;
  const hosts = SHOP_HOSTS[storeId];
  if (hosts && !hosts.includes(parsed.hostname)) return null;
  return parsed.href;
}

/**
 * Libris only: the plain GET cart-add link confirmed against the shop (28 Oct 2026).
 * Product id = the trailing number in the Libris product URL. No other shop gets a
 * cart link (Amazon.de's add-to-cart URL hit a sign-in wall).
 */
export function librisCartUrl(storeId: string, listingUrl: string | null): string | null {
  if (storeId !== 'libris') return null;
  const safe = safeListingUrl('libris', listingUrl);
  if (!safe) return null;
  const m = /\/(\d+)\/?$/.exec(new URL(safe).pathname);
  if (!m) return null;
  return `https://www.libris.ro/ajax/cart?addToCart=true&productId=${m[1]}&quantity=1&strategy=once`;
}

/** Short, stable localStorage key for one list (FNV-1a of its code). */
export function storageKey(code: string): string {
  let h = 0x811c9dc5;
  for (let i = 0; i < code.length; i++) {
    h ^= code.charCodeAt(i);
    h = Math.imul(h, 0x01000193);
  }
  return 'omnibasket.buylist.v1.' + (h >>> 0).toString(36) + '.' + code.length.toString(36);
}

/** Same format as AppComponent.money: 1.234,56 */
export function formatLei(cents: number | null): string {
  if (cents == null) return '';
  const sign = cents < 0 ? '-' : '';
  const abs = Math.abs(cents);
  return sign + Math.floor(abs / 100).toLocaleString('ro-RO') + ',' + String(abs % 100).padStart(2, '0');
}
