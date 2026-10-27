import { NgTemplateOutlet } from '@angular/common';
import { Component } from '@angular/core';
import { CATALOG_BOOKS, CATALOG_STORES, CatalogBook, STORE_NAME } from './catalog';

type EditionMode = 'same' | 'exact';
type Phase = 'entry' | 'reading' | 'result' | 'failed';

interface StoreRow {
  store_id: string;
  items_cents: number;
  shipping_cents: number;
  per_order_fee_cents: number;
  store_total_cents: number;
  threshold_cents?: number;
  threshold_crossed?: boolean;
  item_ids?: string[];
}

interface AssignmentRow {
  item_id: string;
  store_id: string;
  price_cents: number;
  seller_certainty?: string;
}

interface SolveBody {
  currency: string;
  total_cents: number;
  assignment: AssignmentRow[];
  stores: StoreRow[];
  cheapest_per_item: {
    total_cents: number;
    lines: { item_id: string; store_id: string; price_cents: number }[];
    stores: StoreRow[];
  };
  membership: {
    store_id?: string;
    membership_price_cents?: number | null;
    without_membership_total_cents?: number;
    with_membership_total_cents?: number;
  }[];
  source?: string;
  pages?: { store_id: string; item_id: string; status: string; cache?: string }[];
  error?: string;
}

interface PageLine {
  title: string;
  store: string;
  status: string;
}

@Component({
  selector: 'app-root',
  imports: [NgTemplateOutlet],
  templateUrl: './app.component.html',
  styleUrl: './app.component.css',
})
export class AppComponent {
  phase: Phase = 'entry';
  edition: EditionMode = 'same';
  membershipOn = false;
  books: CatalogBook[] = CATALOG_BOOKS.map((book) => ({ ...book, offers: book.offers.map((offer) => ({ ...offer })) }));
  draft = '';
  solution: SolveBody | null = null;
  oneShop: { name: string; total: number } | null = null;
  oneShopComparable = false;
  cacheNotice = false;
  progressDone = 0;
  progressTotal = 0;
  progressTitle = '';
  progressStore = '';
  pagesRead = 0;
  failTitle = 'No recommendation';
  failBody = 'No store page could be read. There is no split and no total.';
  leftOut: string[] = [];
  tradeoff = '';
  membershipVerdict = '';
  private timer: ReturnType<typeof setInterval> | null = null;
  private runToken = 0;

  get membershipNamed(): boolean {
    return (this.solution?.membership?.length ?? 0) > 0;
  }

  get membershipName(): string {
    const row = this.solution?.membership?.[0];
    return row?.store_id ? STORE_NAME[row.store_id] || row.store_id : '';
  }

  get membershipPrice(): number | null {
    const price = this.solution?.membership?.[0]?.membership_price_cents;
    return typeof price === 'number' ? price : null;
  }

  money(cents: number | null | undefined): string {
    const value = cents ?? 0;
    const sign = value < 0 ? '-' : '';
    const abs = Math.abs(value);
    const lei = Math.floor(abs / 100);
    const frac = String(abs % 100).padStart(2, '0');
    return `${sign}${lei.toLocaleString('ro-RO')},${frac} lei`;
  }

  storeName(id: string): string {
    return STORE_NAME[id] || id;
  }

  splitLine(): string {
    if (!this.solution) return '';
    const counts = new Map<string, number>();
    for (const row of this.solution.assignment) {
      counts.set(row.store_id, (counts.get(row.store_id) || 0) + 1);
    }
    const parts = this.solution.stores.map((store) => {
      const n = counts.get(store.store_id) || store.item_ids?.length || 0;
      const noun = n === 1 ? 'book' : 'books';
      return `${n} ${noun} at ${this.storeName(store.store_id)}`;
    });
    return parts.join(', ');
  }

  deltaLine(other: number | null): string {
    if (!this.solution || other == null) return '';
    const gap = other - this.solution.total_cents;
    if (gap === 0) return 'Same total';
    if (gap < 0) return '';
    return `${this.money(gap)} more than the recommendation`;
  }

  shippingLabel(cents: number): string {
    return cents === 0 ? 'Shipping free' : `Shipping ${this.money(cents)}`;
  }

  booksFor(storeId: string): AssignmentRow[] {
    return (this.solution?.assignment || []).filter((row) => row.store_id === storeId && this.titleOf(row.item_id));
  }

  titleOf(id: string): string {
    return this.books.find((book) => book.id === id)?.title ?? '';
  }

  offerOf(itemId: string, storeId: string) {
    return this.books.find((book) => book.id === itemId)?.offers.find((offer) => offer.storeId === storeId);
  }

  isbnLine(itemId: string): string {
    const book = this.books.find((row) => row.id === itemId);
    if (!book || !book.offers.some((offer) => offer.sameStory)) return '';
    const labels = book.offers.map((offer) => `${this.storeName(offer.storeId)} ${offer.isbn13 ?? 'no ISBN printed'}`);
    return `ISBNs read: ${labels.join(' · ')}`;
  }

  chip(itemId: string, storeId: string): string {
    if (this.edition !== 'same') return '';
    const offer = this.offerOf(itemId, storeId);
    if (!offer?.sameStory) return '';
    return 'Same story · another printing';
  }

  addBook(): void {
    const title = this.draft.trim();
    if (!title) return;
    this.books = [...this.books, { id: `added-${this.books.length + 1}`, title, isbn13: null, offers: [] }];
    this.draft = '';
  }

  removeBook(id: string): void {
    this.books = this.books.filter((book) => book.id !== id);
    if (this.books.length === 0) {
      this.phase = 'entry';
      this.solution = null;
    }
  }

  setEdition(mode: EditionMode): void {
    if (this.edition === mode) return;
    this.edition = mode;
    if (this.phase === 'result' || this.phase === 'failed') {
      void this.solveGiven(false);
    }
  }

  setMembership(on: boolean): void {
    if (!this.membershipNamed || this.membershipOn === on) return;
    this.membershipOn = on;
    if (this.solution) {
      void this.solveGiven(false);
    }
  }

  stop(): void {
    this.runToken += 1;
    if (this.timer) clearInterval(this.timer);
    this.phase = 'failed';
    this.failTitle = 'No recommendation';
    this.failBody = 'This run was stopped. Nothing was recommended.';
    this.solution = null;
  }

  async findSplit(): Promise<void> {
    if (this.books.length === 0) return;
    const token = ++this.runToken;
    this.phase = 'reading';
    this.solution = null;
    this.oneShop = null;
    this.cacheNotice = false;
    this.leftOut = [];
    this.progressDone = 0;
    this.progressTotal = 0;
    this.pagesRead = 0;
    this.progressTitle = '';
    try {
      const response = await fetch('/events?source=cache');
      const text = await response.text();
      if (token !== this.runToken) return;
      const events = parseSse(text);
      const errorEvent = events.find((event) => event.event === 'error');
      const pages = events.filter((event) => event.event === 'page').map((event) => event.data as PageLine & { item_id: string; store_id: string; status: string; cache?: string });
      const visible = pages.filter((page) => this.books.some((book) => book.id === page.item_id));
      this.cacheNotice = true;
      if (errorEvent) {
        const data = errorEvent.data as { misses?: { item_id: string; store_id: string; title?: string }[] };
        this.showFailure(this.missCopy(data.misses || []));
        return;
      }
      const failed = visible.filter((page) => page.status !== 'ok' || page.cache === 'miss');
      if (pages.length === 0 || (visible.length > 0 && failed.length === visible.length)) {
        this.showFailure(this.missCopy(failed));
        return;
      }
      const toPlay = visible.length ? visible : pages;
      this.progressTotal = toPlay.length;
      await this.playPages(toPlay, token);
      if (token !== this.runToken) return;
      await this.solveGiven(true);
    } catch {
      if (token !== this.runToken) return;
      this.showFailure('No store page could be read. There is no split and no total.');
    }
  }

  private playPages(pages: { item_id: string; store_id: string; status: string }[], token: number): Promise<void> {
    return new Promise((resolve) => {
      let index = 0;
      this.timer = setInterval(() => {
        if (token !== this.runToken) {
          if (this.timer) clearInterval(this.timer);
          resolve();
          return;
        }
        const page = pages[index];
        this.progressDone = index + 1;
        this.progressTitle = this.titleOf(page.item_id);
        this.progressStore = this.storeName(page.store_id);
        if (page.status === 'ok') this.pagesRead += 1;
        index += 1;
        if (index >= pages.length) {
          if (this.timer) clearInterval(this.timer);
          resolve();
        }
      }, 120);
    });
  }

  private async solveGiven(fromCache: boolean): Promise<void> {
    const items = this.books
      .map((book) => {
        const offers = book.offers.filter((offer) => this.edition === 'same' || (!!book.isbn13 && offer.isbn13 === book.isbn13 && !offer.sameStory));
        return {
          id: book.id,
          offers: offers.map((offer) => ({
            store_id: offer.storeId,
            price_cents: offer.priceCents,
            seller_certainty: offer.sellerCertainty,
          })),
        };
      })
      .filter((item) => item.offers.length > 0);
    this.leftOut = this.books
      .filter((book) => !items.some((item) => item.id === book.id))
      .map((book) => (this.edition === 'exact' ? `${book.title}: No exact edition at the shops that were read.` : book.title));
    if (items.length === 0) {
      this.phase = 'failed';
      this.cacheNotice = fromCache || this.cacheNotice;
      this.failTitle = 'No recommendation';
      this.failBody = 'No store page could be read. There is no split and no total.';
      return;
    }
    const response = await fetch('/solve?source=cache', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        source: 'given',
        stores: CATALOG_STORES.map((store) => ({
          id: store.id,
          currency: store.currency,
          free_shipping_threshold_cents: store.freeShippingThresholdCents,
          shipping_fee_cents: store.shippingFeeCents,
          per_order_fee_cents: store.perOrderFeeCents,
        })),
        items,
      }),
    });
    const body = (await response.json()) as SolveBody;
    if (!response.ok || body.error) {
      this.showFailure(body.error || 'No store page could be read. There is no split and no total.');
      return;
    }
    body.source = 'cache';
    await this.applySolution(body, true);
  }

  private async applySolution(body: SolveBody, fromCache: boolean): Promise<void> {
    const baseline = body.cheapest_per_item?.total_cents ?? body.total_cents;
    if (baseline < body.total_cents) {
      this.showFailure('The result contradicted itself. Nothing is recommended.');
      return;
    }
    this.solution = body;
    this.cacheNotice = fromCache || body.source === 'cache';
    this.tradeoff = this.buildTradeoff(body);
    this.membershipVerdict = this.buildMembership(body);
    this.oneShopComparable = new Set(body.assignment.map((row) => row.store_id)).size > 1;
    this.oneShop = await this.bestOneShop(body);
    if (!this.oneShop) this.oneShopComparable = false;
    this.phase = 'result';
  }

  private missCopy(misses: { item_id: string; store_id: string; title?: string }[]): string {
    const named = misses
      .map((miss) => {
        const fromList = this.books.find((book) => book.id === miss.item_id)?.title;
        const title = fromList || (miss.title && miss.title !== miss.item_id ? miss.title : '');
        if (!title) return '';
        return `${title} at ${this.storeName(miss.store_id)}`;
      })
      .filter((line, index, all) => line && all.indexOf(line) === index);
    if (!named.length) return 'No store page could be read. There is no split and no total.';
    if (named.length === 1) return `${named[0]} could not be read. There is no split and no total.`;
    return `${named.join('; ')} could not be read. There is no split and no total.`;
  }

  private showFailure(text: string): void {
    this.phase = 'failed';
    this.solution = null;
    this.failTitle = 'No recommendation';
    this.failBody = text;
    this.cacheNotice = true;
  }

  private async bestOneShop(body: SolveBody): Promise<{ name: string; total: number } | null> {
    const itemIds = new Set(body.assignment.map((row) => row.item_id));
    const candidates = CATALOG_STORES.filter((store) => {
      return [...itemIds].every((id) => this.books.find((book) => book.id === id)?.offers.some((offer) => offer.storeId === store.id && (this.edition === 'same' || (!!this.books.find((book) => book.id === id)?.isbn13 && !offer.sameStory))));
    });
    let best: { name: string; total: number } | null = null;
    for (const store of candidates) {
      const items = [...itemIds].map((id) => {
        const book = this.books.find((row) => row.id === id)!;
        const offer = book.offers.find((row) => row.storeId === store.id)!;
        return {
          id,
          offers: [{ store_id: store.id, price_cents: offer.priceCents, seller_certainty: offer.sellerCertainty }],
        };
      });
      const response = await fetch('/solve', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          source: 'given',
          stores: [{
            id: store.id,
            currency: store.currency,
            free_shipping_threshold_cents: store.freeShippingThresholdCents,
            shipping_fee_cents: store.shippingFeeCents,
            per_order_fee_cents: store.perOrderFeeCents,
          }],
          items,
        }),
      });
      if (!response.ok) continue;
      const payload = (await response.json()) as SolveBody;
      if (payload.total_cents == null) continue;
      if (!best || payload.total_cents < best.total) best = { name: store.name, total: payload.total_cents };
    }
    return best;
  }

  private buildMembership(body: SolveBody): string {
    if (!body.membership?.length) return '';
    if (!this.membershipOn) return 'Prices are for a shopper without the membership.';
    const row = body.membership[0];
    const withTotal = row.with_membership_total_cents ?? body.total_cents;
    const withoutTotal = row.without_membership_total_cents ?? body.total_cents;
    if (withTotal === withoutTotal) {
      return 'Having it does not change this basket. The split and the total stay the same.';
    }
    return `Having it changes the answer. The total would be ${this.money(withTotal)} instead of ${this.money(withoutTotal)}.`;
  }

  private buildTradeoff(body: SolveBody): string {
    const storeIds = new Set(body.assignment.map((row) => row.store_id));
    if (storeIds.size === 1) {
      const only = this.storeName([...storeIds][0]);
      const readable = new Set((body.pages || []).filter((page) => page.status === 'ok').map((page) => page.store_id));
      if (body.pages && readable.size <= 1) {
        return `Only ${only} could be priced for this basket. This is not a split. The total is what that shop charges, including its shipping.`;
      }
      const saved = (this.oneShop?.total ?? body.total_cents) - body.total_cents;
      if (saved === 0 && body.cheapest_per_item.total_cents === body.total_cents) {
        return `Buying everything at ${only} costs the same as splitting. One order is the simpler way to pay it.`;
      }
      return `Buying everything at ${only} is cheaper than splitting, because one shipping charge beats several smaller orders. The total is ${this.money(Math.max(saved, body.cheapest_per_item.total_cents - body.total_cents))} less than the cheapest split.`;
    }
    const moves = body.assignment
      .map((row) => {
        const base = body.cheapest_per_item.lines.find((line) => line.item_id === row.item_id);
        if (!base || base.store_id === row.store_id) return null;
        const dest = body.stores.find((store) => store.store_id === row.store_id);
        const before = body.cheapest_per_item.stores.find((store) => store.store_id === row.store_id);
        const shippingSaved = (before?.shipping_cents ?? 0) - (dest?.shipping_cents ?? 0);
        if (shippingSaved <= 0) return null;
        return { row, delta: row.price_cents - base.price_cents, shippingSaved };
      })
      .filter((row): row is { row: AssignmentRow; delta: number; shippingSaved: number } => !!row && row.delta > 0)
      .sort((a, b) => b.delta - a.delta);
    const net = body.cheapest_per_item.total_cents - body.total_cents;
    if (moves.length && net > 0) {
      const lead = moves[0];
      const dest = body.stores.find((store) => store.store_id === lead.row.store_id);
      const before = body.cheapest_per_item.stores.find((store) => store.store_id === lead.row.store_id);
      const shippingBefore = (dest ? body.cheapest_per_item.stores.find((store) => store.store_id === dest.store_id)?.shipping_cents : 0) ?? 0;
      const shippingAfter = dest?.shipping_cents ?? 0;
      const shippingSaved = lead.shippingSaved;
      const threshold = dest?.threshold_cents;
      const thresholdLabel = threshold != null ? `the free-shipping threshold (${this.money(threshold)})` : 'the free-shipping threshold';
      const others = moves.length - 1;
      const extra = others === 1
        ? ' 1 other book also moves to reach it.'
        : others > 1
          ? ` ${others} other books also move to reach it.`
          : '';
      return `Buying “${this.titleOf(lead.row.item_id)}” at ${this.storeName(lead.row.store_id)} costs ${this.money(lead.delta)} more than the cheapest listing.${extra} That brings the ${this.storeName(lead.row.store_id)} order to ${thresholdLabel}, so shipping goes from ${this.money(shippingBefore)} to ${this.money(shippingAfter)}. You pay ${this.money(lead.delta)} more for that book and save ${this.money(shippingSaved)} on shipping. This basket is ${this.money(net)} cheaper than buying each book at its cheapest shop.`;
    }
    if (net === 0 && moves.length === 0) {
      return 'Buying each book at its cheapest shop is already the lowest total. Moving a book to reach free shipping would cost more than the shipping it removes.';
    }
    return 'Buying each book at its cheapest shop is already the lowest total. Moving a book to reach free shipping would cost more than the shipping it removes.';
  }
}

function parseSse(text: string): { event: string; data: unknown }[] {
  const blocks = text.split('\n\n').map((block) => block.trim()).filter(Boolean);
  const events = [];
  for (const block of blocks) {
    let event = 'message';
    const dataLines = [];
    for (const line of block.split('\n')) {
      if (line.startsWith('event:')) event = line.slice(6).trim();
      if (line.startsWith('data:')) dataLines.push(line.slice(5).trim());
    }
    if (!dataLines.length) continue;
    events.push({ event, data: JSON.parse(dataLines.join('\n')) });
  }
  return events;
}
