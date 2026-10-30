import { Injectable } from '@angular/core';
import { LiveOffer } from './live';

/** The shopper's basket: the books they picked, and nothing else. Kept in localStorage. */
export const BASKET_KEY = 'omnibasket.basket.v1';

export interface BasketOffer {
  store_id: string;
  price_cents: number;
  seller_certainty: string;
  edition: string | null;
  listing_url: string | null;
  read_at: string | null;
  in_stock: boolean | null;
}

/** A shop's delivery rules, in the shape POST /solve (source=given) takes. */
export interface BasketShop {
  id: string;
  currency: string;
  free_shipping_threshold_cents: number;
  shipping_fee_cents: number | null;
  per_order_fee_cents: number;
  read_at: string | null;
}

export interface BasketItem {
  id: string;
  isbn: string;
  title: string;
  author: string | null;
  /** Priced offers the live read returned. Empty: no shop lists the ISBN. */
  offers: BasketOffer[];
  /** Every shop's outcome from the live read, kept for the per-shop rows. */
  live_offers: LiveOffer[];
}

interface LivePayloadLike {
  books?: { item_id: string; isbn13: string | null; title?: string; shops?: Record<string, unknown>[] }[];
  shops?: Record<string, unknown>[];
  live_offers?: LiveOffer[];
  joined_item_id?: string;
  joined_title?: string;
}

export interface GivenBody {
  source: 'given';
  stores: BasketShop[];
  items: { id: string; title: string; isbn13: string; offers: BasketOffer[] }[];
}

export function itemId(isbn: string): string {
  return 'book-' + isbn;
}

/** The items that can be priced: at least one offer in a shop whose delivery rules are known. */
export function placeable(items: BasketItem[], shops: BasketShop[]): BasketItem[] {
  const ids = new Set(shops.map((s) => s.id));
  return items.filter((i) => i.offers.some((o) => ids.has(o.store_id)));
}

/** The /solve body for exactly these books. null when there is nothing to price. */
export function buildGivenBody(items: BasketItem[], shops: BasketShop[]): GivenBody | null {
  const ids = new Set(shops.map((s) => s.id));
  const rows = placeable(items, shops).map((i) => ({
    id: i.id,
    title: i.title,
    isbn13: i.isbn,
    offers: i.offers.filter((o) => ids.has(o.store_id)),
  }));
  if (!rows.length) return null;
  const used = new Set(rows.flatMap((r) => r.offers.map((o) => o.store_id)));
  return { source: 'given', stores: shops.filter((s) => used.has(s.id)), items: rows };
}

@Injectable({ providedIn: 'root' })
export class BasketService {
  items: BasketItem[] = [];
  shops: BasketShop[] = [];

  constructor() {
    this.load();
  }

  private load(): void {
    try {
      const raw = JSON.parse(localStorage.getItem(BASKET_KEY) || 'null');
      if (raw && Array.isArray(raw.items)) {
        this.items = raw.items;
        this.shops = Array.isArray(raw.shops) ? raw.shops : [];
      }
    } catch {
      this.items = [];
      this.shops = [];
    }
  }

  private save(): void {
    try {
      localStorage.setItem(BASKET_KEY, JSON.stringify({ items: this.items, shops: this.shops }));
    } catch {
      /* storage full or blocked: the basket still works for this visit */
    }
  }

  get count(): number {
    return this.items.length;
  }

  has(isbn: string): boolean {
    return this.items.some((i) => i.isbn === isbn);
  }

  /** Add (or refresh) the book a live read was run for. Only that book joins; nothing else comes with it. */
  addFromLive(input: object, isbn: string, fallbackTitle: string, author: string | null = null): BasketItem {
    const payload = input as LivePayloadLike;
    const live = payload.live_offers || [];
    const row = (payload.books || []).find((b) => b.item_id === payload.joined_item_id) || (payload.books || []).find((b) => b.isbn13 === isbn);
    let offers: BasketOffer[] = (row?.shops || [])
      .filter((o) => typeof o['price_cents'] === 'number')
      .map((o) => ({
        store_id: String(o['store_id']),
        price_cents: o['price_cents'] as number,
        seller_certainty: typeof o['seller_certainty'] === 'string' ? (o['seller_certainty'] as string) : 'unknown',
        edition: (o['edition'] as string | null) ?? null,
        listing_url: (o['listing_url'] as string | null) ?? null,
        read_at: (o['read_at'] as string | null) ?? null,
        in_stock: o['status'] === 'out_of_stock' ? false : null,
      }));
    if (!offers.length) {
      offers = live
        .filter((o) => o.price_cents != null)
        .map((o) => ({ store_id: o.store_id, price_cents: o.price_cents as number, seller_certainty: 'unknown', edition: null, listing_url: o.listing_url, read_at: null, in_stock: null }));
    }
    const old = this.items.find((i) => i.isbn === isbn);
    // A re-read keeps what an earlier read priced: a shop that answers now overrides its old row, a shop
    // that says nothing keeps it. A book is never made worse by being added twice.
    if (old) {
      const fresh = new Set(offers.map((o) => o.store_id));
      offers = [...old.offers.filter((o) => !fresh.has(o.store_id)), ...offers];
    }
    const liveMerged: LiveOffer[] = old
      ? [...old.live_offers.filter((o) => !live.some((n) => n.store_id === o.store_id)), ...live]
      : live;
    const title = (payload.joined_title || fallbackTitle || old?.title || '').trim() || 'ISBN ' + isbn;
    const item: BasketItem = { id: itemId(isbn), isbn, title, author: author || old?.author || null, offers, live_offers: liveMerged };
    this.items = [...this.items.filter((i) => i.isbn !== isbn), item];
    this.mergeShops(payload.shops || []);
    this.save();
    return item;
  }

  /** A book whose read gave nothing: it is listed in the basket, not priced, and the books already priced stay as they were. */
  addUnpriced(isbn: string, title: string, author: string | null = null): BasketItem {
    return this.addFromLive({}, isbn, title, author);
  }

  private mergeShops(rows: Record<string, unknown>[]): void {
    const next = new Map(this.shops.map((s) => [s.id, s]));
    for (const r of rows) {
      const threshold = r['free_delivery_threshold_cents'];
      if (!r['priced'] || typeof threshold !== 'number') continue;
      const id = String(r['store_id']);
      next.set(id, {
        id,
        currency: (r['currency'] as string) || 'RON',
        free_shipping_threshold_cents: threshold,
        shipping_fee_cents: (r['delivery_cents'] as number | null) ?? null,
        per_order_fee_cents: (r['order_fee_cents'] as number | null) ?? 0,
        read_at: (r['read_at'] as string | null) ?? null,
      });
    }
    this.shops = [...next.values()];
  }

  remove(id: string): void {
    this.items = this.items.filter((i) => i.id !== id);
    this.save();
  }

  clear(): void {
    this.items = [];
    this.save();
  }

  placeable(): BasketItem[] {
    return placeable(this.items, this.shops);
  }

  /** Books that cannot be priced: no offer anywhere, or no offer in a shop with known delivery rules. */
  unplaced(): BasketItem[] {
    const ok = new Set(this.placeable().map((i) => i.id));
    return this.items.filter((i) => !ok.has(i.id));
  }

  givenBody(): GivenBody | null {
    return buildGivenBody(this.items, this.shops);
  }
}
