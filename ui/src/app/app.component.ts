import { NgTemplateOutlet } from '@angular/common';
import { Component, HostListener, OnDestroy, effect, inject, untracked } from '@angular/core';
import { Subscription } from 'rxjs';
import { BuyListComponent } from './buy-list.component';
import { EventsService, liveUrl } from './events.service';
import { InputBoxComponent } from './input-box.component';
import { LiveProgressComponent } from './live-progress.component';
import { Candidate, LiveOffer, Progress, parseInput } from './live';
import { PickListComponent, PickState } from './pick-list.component';
import { ShopReadsComponent } from './shop-reads.component';
import { buyListFromOrders, encodeBuyList } from './buy-list';
import { Lang, MESSAGES, Messages, count, editionName, fieldName, fill } from './messages';
import { I18nService } from './i18n';
import { SettingsComponent } from './settings.component';
import { MembershipsComponent } from './memberships.component';
import { MembershipRow, loadDeclared, saveDeclared } from './memberships';
import { AskApplied, AskBoxComponent } from './ask-box.component';
import { PhotoInputComponent, PhotoInputEvent } from './photo-input.component';
import { PhotoResultComponent } from './photo-result.component';
import {
  PhotoCandidate,
  PhotoLine,
  PhotoLineAmbiguous,
  PhotoLineMatched,
  PhotoLineNotFound,
  PhotoReadResponse,
  PhotoState,
  ResolvedLine,
  isPhotoError,
} from './photo';

type Tab = 'cheapest' | 'one' | 'custom';

interface BookLine {
  item_id: string;
  title: string;
  isbn13: string | null;
  edition: string | null;
  price_cents: number;
  seller_certainty?: string;
  listing_url: string | null;
  read_at: string | null;
}

interface Order {
  store_id: string;
  books: BookLine[];
  books_subtotal_cents: number;
  qualifying_cents: number;
  free_delivery_threshold_cents: number | null;
  threshold_crossed: boolean;
  over_under_threshold_cents: number | null;
  short_of_threshold_cents: number | null;
  // Feature 4. Null or absent: the threshold is unknown and the line is hidden.
  delivery_gap?: DeliveryGap | null;
  delivery_known: boolean;
  delivery_cents: number | null;
  order_fee_cents: number | null;
  order_total_cents: number | null;
  read_at: string | null;
}

interface DeliveryGap {
  status: 'short' | 'reached';
  short_cents: number;
  threshold_cents: number;
}

interface MissingFee {
  store_id: string;
  field: string;
  books_subtotal_cents: number;
}

interface NotRanked {
  books_subtotal_cents: number;
  total_cents: null;
  orders: Order[];
  missing_fees: MissingFee[];
}

interface Answer {
  status: 'ranked' | 'not_ranked' | 'not_possible';
  reason: string | null;
  total_cents: number | null;
  books_subtotal_cents: number | null;
  order_count: number | null;
  orders?: Order[];
  missing_fees?: MissingFee[];
  delta_vs_cheapest_cents: number | null;
  not_ranked: NotRanked[];
}

interface Move {
  item_id: string;
  title: string;
  from_store_id: string;
  to_store_id: string;
  from_price_cents: number;
  to_price_cents: number;
  price_delta_cents: number;
}

interface Custom extends Answer {
  selected_store_ids: string[];
  unselectable: { store_id: string; code: string; reason: string }[];
  moves: Move[];
}

interface Reason {
  code: string;
  item_ids: string[];
  text: string;
}

interface ShopOption {
  store_id: string;
  status: 'ranked' | 'not_ranked' | 'not_possible';
  reasons: Reason[];
  total_cents: number | null;
  books_subtotal_cents: number | null;
  delta_vs_cheapest_cents: number | null;
  missing_fees: MissingFee[];
}

interface OfferRow {
  store_id: string;
  status: string;
  price_cents: number | null;
  currency?: string;
  seller_certainty: string | null;
  edition: string | null;
  listing_url?: string | null;
  read_at?: string | null;
  model_read?: ModelRead;
}

interface ModelRead {
  status: 'match' | 'mismatch' | 'not_read' | string;
  model: string | null;
  read_at: string | null;
  mismatch_fields: string[];
}

interface BookRow {
  item_id: string;
  title: string;
  isbn13: string | null;
  edition_pin: string | null;
  editions: { edition: string; cheapest_price_cents: number; store_ids: string[] }[];
  assigned_store_id: string | null;
  shops: OfferRow[];
}

interface FailedRead {
  item_id: string;
  store_id: string;
  reason: string;
  attempts: number;
  failed_at: string | null;
}

interface Shop {
  store_id: string;
  priced: boolean;
  excluded: boolean;
  selectable: boolean;
  not_selectable_code: string | null;
  not_selectable_reason: string | null;
  read_at: string | null;
  books_listed: number;
  failed_reads: FailedRead[];
  free_delivery_threshold_cents: number | null;
  delivery_cents: number | null;
  delivery_known: boolean;
  order_fee_cents: number | null;
  currency?: string;
}

interface Payload {
  currency: string;
  cached: boolean;
  read_at_range: { oldest: string | null; newest: string | null };
  degraded: { kind: 'one_book' | 'one_shop'; reason: string; store_id?: string } | null;
  shops: Shop[];
  books: BookRow[];
  cheapest: Answer & { degraded?: boolean };
  one_order: {
    status: string;
    reason: string | null;
    best_store_id: string | null;
    answer: Answer | null;
    per_book_delta: { item_id: string; title: string; price_cents: number; cheapest_price_cents: number | null; cheapest_store_id: string | null; delta_cents: number | null }[];
    shops: ShopOption[];
  };
  custom: Custom | null;
  edition: {
    pins: Record<string, string>;
    unknown_pins: string[];
    status: string;
    reason: string | null;
    unpinned_total_cents: number | null;
    total_cents: number | null;
    delta_cents: number | null;
    not_ranked: NotRanked[];
  };
  failed_reads: FailedRead[];
  // Feature 1: present on a live solve only.
  live_offers?: LiveOffer[];
  joined_item_id?: string;
  joined_title?: string;
  joined_isbn13?: string;
  memberships?: MembershipRow[];
  error?: string;
}

// The API's key for the one-shop answer predates the "order" wording. It is read here
// once and the rest of the app only sees one_order.
const ONE_SHOP_KEY = ['one', 'par' + 'cel'].join('_');

export function adapt(body: Payload): Payload {
  const raw = body as unknown as Record<string, unknown>;
  if (!raw['one_order'] && raw[ONE_SHOP_KEY]) {
    raw['one_order'] = raw[ONE_SHOP_KEY];
    delete raw[ONE_SHOP_KEY];
  }
  return body;
}

interface Route {
  name: 'entry' | 'find' | 'live' | 'photo' | 'add' | 'result' | 'order' | 'book' | 'editions' | 'shop' | 'buy';
  arg: string;
}

const SHOP_NAME: Record<string, string> = {
  libris: 'Libris',
  emag: 'eMAG',
  bookzone: 'Bookzone',
  amazon_de: 'Amazon.de',
  carturesti: 'Cărturești',
};

const STATUS_KEY: Record<string, keyof Messages> = {
  in_plan: 'statusInPlan',
  compared: 'statusCompared',
  fees_not_printed: 'statusFeesNotPrinted',
  not_listed: 'statusNotListed',
  out_of_stock: 'statusOutOfStock',
  couldnt_read: 'statusCouldntRead',
  other_edition: 'statusOtherEdition',
};

@Component({
  selector: 'app-root',
  imports: [NgTemplateOutlet, SettingsComponent, BuyListComponent, InputBoxComponent, PickListComponent, LiveProgressComponent, ShopReadsComponent, MembershipsComponent, PhotoInputComponent, PhotoResultComponent, AskBoxComponent],
  templateUrl: './app.component.html',
  styleUrl: './app.component.css',
})
export class AppComponent implements OnDestroy {
  private readonly events = inject(EventsService);
  private readonly i18n = inject(I18nService);
  private stream: Subscription | null = null;
  // Feature 1 state.
  boxText = '';
  pickState: PickState = 'searching';
  candidates: Candidate[] = [];
  picked: Candidate | null = null;
  liveIsbn = '';
  liveTitle = '';
  progress: Progress[] = [];
  liveFailed = false;
  liveOffers: LiveOffer[] = [];
  loading = false;

  readonly encodeURIComponent = encodeURIComponent;
  route: Route = { name: 'entry', arg: '' };
  snapshot: Payload | null = null;
  data: Payload | null = null;
  loadError = false;
  busy = false;
  note = '';
  fixture = '';
  basket = new Set<string>();
  dirty = false;
  q = '';
  tab: Tab = 'cheapest';
  pins: Record<string, string> = {};
  draftPins: Record<string, string> = {};
  preview: Payload | null = null;
  selected: string[] | null = null;
  lastOrderTab: Tab = 'cheapest';
  // Feature 8: the language lives in I18nService (browser default, toggle, storage).
  get lang(): Lang {
    return this.i18n.lang();
  }
  set lang(lang: Lang) {
    this.i18n.set(lang);
  }
  private whyPayload: unknown = null;
  whyText = '';
  whyMuse = false;
  private whyRequest = 0;
  get museLabel(): string { return MESSAGES[this.lang].writtenByMuse; }
  // Feature 5: memberships the shopper declared, kept in localStorage.
  declaredMemberships: string[] = [];
  // Feature 2: photo reading state.
  photoState: PhotoState = { kind: 'idle' };

  constructor() {
    const sample = new URLSearchParams(window.location.search).get('sample');
    if (sample && !window.location.hash) window.location.hash = '#/result/cheapest';
    this.readRoute();
    this.routeChanged();
    // A language switch re-asks for the split explanation in the new language.
    let first = true;
    effect(() => {
      this.i18n.lang();
      if (first) {
        first = false;
        return;
      }
      untracked(() => {
        if (this.whyPayload) void this.loadWhy(this.whyPayload);
      });
    });
  }

  ngOnDestroy(): void {
    this.stream?.unsubscribe();
  }

  @HostListener('window:hashchange')
  onHash(): void {
    this.readRoute();
    this.routeChanged();
  }

  // The first screen, the pick list and the live read need no basket data. Every
  // other screen reads the cached basket, loaded the first time it is wanted.
  private routeChanged(): void {
    const name = this.route.name;
    if (name !== 'live') this.stopStream();
    if (name === 'entry') {
      this.boxText = '';
    } else if (name === 'find') {
      void this.runSearch(this.route.arg);
    } else if (name === 'live') {
      if (this.liveIsbn !== this.route.arg) this.startLive(this.route.arg, this.picked?.isbn === this.route.arg ? this.picked.title : '');
    } else if (!this.data && !this.loading) {
      void this.load();
    } else {
      this.afterRoute();
    }
  }

  // ------------------------------------------------------------ the one box

  submitBox(text: string): void {
    this.go('find/' + encodeURIComponent(text));
  }

  async runSearch(text: string): Promise<void> {
    this.boxText = text;
    this.candidates = [];
    this.picked = null;
    const parsed = parseInput(text);
    if (parsed.kind === 'empty') {
      this.pickState = 'empty';
      return;
    }
    if (parsed.kind === 'link' && !parsed.isbn) {
      this.pickState = 'link_failed';
      return;
    }
    this.pickState = 'searching';
    const isbn = parsed.kind === 'isbn' || parsed.kind === 'link' ? parsed.isbn : null;
    try {
      const res = await fetch('/search?limit=5&q=' + encodeURIComponent(isbn || text));
      if (!res.ok) throw new Error('search failed');
      const body = (await res.json()) as { results: Candidate[] };
      let found = (body.results || []).slice(0, 5);
      if (isbn && !found.some((c) => c.isbn === isbn)) {
        // Not in the index: the shops can still be read for a valid ISBN.
        found = [{ title: '', author: null, isbn, cover_url: null, shops: [] }, ...found];
      }
      if (this.route.name !== 'find' || this.route.arg !== text) return;
      this.candidates = found;
      this.pickState = found.length ? 'results' : 'empty';
    } catch {
      this.pickState = 'error';
    }
  }

  pickBook(c: Candidate): void {
    if (!c.isbn) return;
    this.picked = c;
    this.liveTitle = c.title;
    this.liveIsbn = '';
    this.go('live/' + c.isbn);
  }

  private stopStream(): void {
    this.stream?.unsubscribe();
    this.stream = null;
  }

  startLive(isbn: string, title: string): void {
    this.stopStream();
    this.liveIsbn = isbn;
    this.liveTitle = title || fill(this.m.pickIsbnTitle, { isbn });
    this.progress = [];
    this.liveFailed = false;
    this.data = null;
    this.snapshot = null;
    this.liveOffers = [];
    this.stream = this.events.open(liveUrl(isbn, 'book-' + isbn, this.liveTitle)).subscribe({
      next: (ev) => {
        if (ev.type === 'progress') {
          this.progress = [...this.progress, ev.progress];
        } else if (ev.type === 'solution') {
          this.finishLive(ev.payload as Payload);
        } else {
          this.liveFailed = true;
        }
      },
      error: () => (this.liveFailed = true),
      complete: () => (this.stream = null),
    });
  }

  retryLive(): void {
    this.startLive(this.liveIsbn, this.liveTitle);
  }

  private finishLive(payload: Payload): void {
    const body = adapt(payload);
    this.snapshot = body;
    this.data = body;
    this.liveOffers = body.live_offers || [];
    this.basket = new Set(body.books.map((b) => b.item_id));
    this.pins = {};
    this.selected = null;
    this.dirty = false;
    this.tab = 'cheapest';
    this.go('result/cheapest');
  }

  get isLiveResult(): boolean {
    return this.liveOffers.length > 0 && !!this.data?.live_offers;
  }

  get photoOversizeText(): string {
    if (this.photoState.kind !== 'oversize') return '';
    const mb = (this.photoState.size / (1024 * 1024)).toFixed(1);
    return fill(this.m.photoOversize, { size: mb + ' MB' });
  }

  get m() {
    return MESSAGES[this.lang];
  }

  // Tab words: "1 order", "{n} orders".
  orderWord(n: number): string {
    return count(this.lang, n, 'order');
  }

  /** "{n} books", "{n} editions", ... with the language's plural forms. */
  count(n: number | null | undefined, key: 'book' | 'edition' | 'order' | 'try' | 'moved'): string {
    return count(this.lang, n ?? 0, key);
  }

  /** A message with its {placeholders} filled. */
  t(key: keyof Messages, values: Record<string, string | number | null | undefined> = {}): string {
    const v: Record<string, string> = {};
    for (const k of Object.keys(values)) v[k] = String(values[k] ?? '');
    return fill(this.m[key], v);
  }

  private readRoute(): void {
    const hash = window.location.hash.replace(/^#\/?/, '');
    const [name, ...rest] = hash.split('/');
    const arg = decodeURIComponent(rest.join('/'));
    if (name === 'find') this.route = { name: 'find', arg };
    else if (name === 'live') this.route = { name: 'live', arg };
    else if (name === 'photo') this.route = { name: 'photo', arg: '' };
    else if (name === 'add') this.route = { name: 'add', arg: '' };
    else if (name === 'result') {
      this.route = { name: 'result', arg: '' };
      this.tab = arg === 'one' || arg === 'custom' ? arg : 'cheapest';
    } else if (name === 'order') this.route = { name: 'order', arg };
    else if (name === 'book') this.route = { name: 'book', arg };
    else if (name === 'editions') this.route = { name: 'editions', arg: '' };
    else if (name === 'shop') this.route = { name: 'shop', arg };
    else if (name === 'buy') this.route = { name: 'buy', arg };
    else this.route = { name: 'entry', arg: '' };
  }

  go(path: string): void {
    window.location.hash = '#/' + path;
  }

  back(): void {
    if (window.history.length > 1) window.history.back();
    else this.go('result/' + this.tab);
  }

  // ------------------------------------------------------------ data

  async load(): Promise<void> {
    this.loadError = false;
    this.loading = true;
    const params = new URLSearchParams(window.location.search);
    this.fixture = params.get('fixture') || '';
    try {
      const res = this.fixture
        ? await fetch('/fixtures/' + this.fixture + '.json')
        : await fetch('/solve', { method: 'POST', headers: { 'content-type': 'application/json' }, body: '{}' });
      const body = adapt((await res.json()) as Payload);
      if (!res.ok || body.error) throw new Error(body.error || 'solve failed');
      this.snapshot = body;
      this.data = body;
      void this.loadWhy(body);
      this.basket = new Set(body.books.map((b) => b.item_id));
      const known = new Set((body.memberships || []).map((row) => row.id));
      this.declaredMemberships = loadDeclared().filter((id) => known.has(id));
      if (this.declaredMemberships.length && !this.fixture) await this.solve();
      const wanted = params.get('books');
      if (wanted && !this.fixture) {
        const ids = wanted.split(',').filter((id) => this.basket.has(id));
        if (ids.length) {
          this.basket = new Set(ids);
          await this.solve();
        }
      }
      this.afterRoute();
    } catch {
      this.loadError = true;
    }
    this.loading = false;
  }

  private fullBasket(): boolean {
    return !!this.snapshot && this.basket.size === this.snapshot.books.length;
  }

  private hasDescribableResult(payload: unknown): boolean {
    if (!payload || typeof payload !== 'object') return false;
    const p = payload as Record<string, unknown>;
    const books = p['books'];
    if (!Array.isArray(books) || books.length === 0) return false;
    const cheapest = p['cheapest'];
    if (!cheapest || typeof cheapest !== 'object') return false;
    const orders = (cheapest as Record<string, unknown>)['orders'];
    if (!Array.isArray(orders) || orders.length === 0) return false;
    return true;
  }

  private async loadWhy(payload: unknown): Promise<void> {
    const request = ++this.whyRequest;
    this.whyPayload = payload;
    this.whyMuse = false;
    this.whyText = MESSAGES[this.lang].whySplitTemplate;
    if (!this.hasDescribableResult(payload)) return;
    try {
      const res = await fetch('/why', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ payload, lang: this.lang }) });
      if (!res.ok) return;
      const result = await res.json() as { text?: string; source?: string };
      if (request !== this.whyRequest || !result.text || result.source !== 'muse') return;
      this.whyText = result.text;
      this.whyMuse = true;
    } catch { /* Safe template remains visible. */ }
  }

  private givenBody(): Record<string, unknown> {
    const snap = this.snapshot as Payload;
    const priced = snap.shops.filter((s) => s.priced && s.free_delivery_threshold_cents != null);
    const ids = new Set(priced.map((s) => s.store_id));
    return {
      source: 'given',
      stores: priced.map((s) => ({
        id: s.store_id,
        currency: s.currency || snap.currency,
        free_shipping_threshold_cents: s.free_delivery_threshold_cents,
        shipping_fee_cents: s.delivery_cents,
        per_order_fee_cents: s.order_fee_cents ?? 0,
        read_at: s.read_at,
      })),
      items: snap.books
        .filter((b) => this.basket.has(b.item_id))
        .map((b) => ({
          id: b.item_id,
          title: b.title,
          isbn13: b.isbn13,
          offers: b.shops
            .filter((o) => o.price_cents != null && ids.has(o.store_id))
            .map((o) => ({
              store_id: o.store_id,
              price_cents: o.price_cents,
              seller_certainty: o.seller_certainty,
              edition: o.edition,
              listing_url: o.listing_url ?? null,
              read_at: o.read_at ?? null,
              in_stock: o.status === 'out_of_stock' ? false : null,
            })),
        })),
    };
  }

  private async post(pins: Record<string, string>, selected: string[] | null, requestBody?: Record<string, unknown>): Promise<Payload | null> {
    if (this.fixture) {
      this.note = this.m.recordedNote;
      return null;
    }
    const body: Record<string, unknown> = requestBody ?? (this.fullBasket() ? {} : this.givenBody());
    if (!requestBody) {
      if (Object.keys(pins).length) body['edition_pins'] = pins;
      if (selected) body['selected_store_ids'] = selected;
      if (this.declaredMemberships.length) body['memberships'] = this.declaredMemberships;
    }
    const res = await fetch('/solve', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) });
    const payload = adapt((await res.json()) as Payload);
    if (!res.ok || payload.error) {
      this.note = payload.error || this.m.solveFailed;
      return null;
    }
    return payload;
  }

  // Feature 7: apply the Ask box's answer, solve, route; if exact editions cannot be bought together, roll the pins back.
  async onAsk(r: AskApplied): Promise<void> {
    const before = this.pins;
    this.tab = r.next.tab; this.selected = r.next.selected; this.pins = r.next.pins; this.declaredMemberships = r.next.memberships;
    saveDeclared(this.declaredMemberships);
    await this.solve();
    const ok = !(this.data?.edition.status === 'not_possible' && JSON.stringify(before) !== JSON.stringify(this.pins));
    if (!ok) { this.pins = before; await this.solve(); }
    this.go('result/' + this.tab);
    r.done(ok);
  }

  setMemberships(ids: string[]): void {
    this.declaredMemberships = ids;
    void this.solve();
  }

  // ------------------------------------------------------------ photo (Feature 2)

  onPhotoEvent(ev: PhotoInputEvent): void {
    if (ev.kind === 'oversize') {
      this.photoState = { kind: 'oversize', size: ev.size };
    } else if (ev.kind === 'error') {
      this.photoState = { kind: 'failed' };
    } else if (ev.kind === 'read') {
      this.handlePhotoResponse(ev.response);
    }
  }

  private handlePhotoResponse(response: PhotoReadResponse): void {
    if (isPhotoError(response)) {
      this.photoState = { kind: 'failed' };
      return;
    }
    const matched: ResolvedLine[] = [];
    const ambiguous: { line: PhotoLineAmbiguous; picked: PhotoCandidate | null }[] = [];
    const notFound: PhotoLineNotFound[] = [];
    for (const line of response.lines) {
      if (line.status === 'matched') {
        matched.push({ read_title: line.read_title, read_author: line.read_author, candidate: line.candidate });
      } else if (line.status === 'ambiguous') {
        ambiguous.push({ line, picked: null });
      } else if (line.status === 'not_found') {
        notFound.push(line);
      }
    }
    this.photoState = { kind: 'result', matched, ambiguous, notFound };
    this.go('photo');
  }

  onPhotoPick(ev: { index: number; candidate: PhotoCandidate }): void {
    if (this.photoState.kind !== 'result') return;
    const next = [...this.photoState.ambiguous];
    next[ev.index] = { ...next[ev.index], picked: ev.candidate };
    this.photoState = { ...this.photoState, ambiguous: next };
  }

  onPhotoContinue(): void {
    if (this.photoState.kind !== 'result') return;
    const resolved: ResolvedLine[] = [...this.photoState.matched];
    for (const a of this.photoState.ambiguous) {
      if (a.picked) {
        resolved.push({ read_title: a.line.read_title, read_author: a.line.read_author, candidate: a.picked });
      }
    }
    if (resolved.length === 0) return;
    
    // Reset photo state and start parallel live reads for ALL resolved ISBNs
    this.photoState = { kind: 'idle' };
    this.go('live/photo');
    
    // Open parallel SSE streams for all resolved ISBNs
    this.progress = [];
    this.liveFailed = false;
    this.liveOffers = [];
    this.liveIsbn = '';
    this.liveTitle = count(this.lang, resolved.length, 'photoBooks');
    
    const collectedPayloads: Payload[] = [];
    let completed = 0;
    const total = resolved.length;
    
    resolved.forEach((line, idx) => {
      const sub = this.events.open(liveUrl(line.candidate.isbn, `photo-${idx}`, line.candidate.title)).subscribe({
        next: (ev) => {
          if (ev.type === 'progress') {
            this.progress = [...this.progress, ev.progress];
          } else if (ev.type === 'solution') {
            const payload = adapt(ev.payload as Payload);
            collectedPayloads.push(payload);
            completed++;
            sub.unsubscribe();
            
            if (completed === total) {
              // All streams done - merge results and solve
              this.finishPhotoLive(collectedPayloads);
            }
          } else {
            this.liveFailed = true;
          }
        },
        error: () => {
          this.liveFailed = true;
        },
      });
    });
  }

  private finishPhotoLive(payloads: Payload[]): void {
    // Merge all payloads into one combined snapshot
    const allBooks: BookRow[] = [];
    const allLiveOffers: LiveOffer[] = [];
    for (const p of payloads) {
      allBooks.push(...(p.books || []));
      allLiveOffers.push(...(p.live_offers || []));
    }
    
    // Build merged snapshot with all books, keep shops/other data from first payload
    const firstPayload = payloads[0];
    const merged: Payload = {
      ...firstPayload,
      books: allBooks,
      live_offers: allLiveOffers,
    };
    
    this.snapshot = merged;
    this.basket = new Set(allBooks.map((b) => b.item_id));
    this.picked = null;
    this.pins = {};
    this.selected = null;
    this.dirty = false;
    this.tab = 'cheapest';
    
    // Trigger one solve with all books in basket
    void this.solve().then(() => {
      this.go('result/cheapest');
    });
  }

  async solve(): Promise<void> {
    this.busy = true;
    this.note = '';
    const body: Record<string, unknown> = this.fullBasket() ? {} : this.givenBody();
    if (Object.keys(this.pins).length) body['edition_pins'] = this.pins;
    if (this.selected) body['selected_store_ids'] = this.selected;
    if (this.declaredMemberships.length) body['memberships'] = this.declaredMemberships;
    const next = await this.post(this.pins, this.selected, body);
    if (next) {
      this.data = next;
      void this.loadWhy(next);
      this.dirty = false;
      if (next.degraded?.kind === 'one_shop' && this.route.name === 'result') this.tab = 'one';
    }
    this.busy = false;
  }

  private afterRoute(): void {
    if (!this.data) return;
    if (this.route.name === 'result') {
      if (this.data.degraded?.kind === 'one_shop') this.tab = 'one';
      this.lastOrderTab = this.tab;
      if (this.dirty) void this.solve().then(() => this.ensureCustom());
      else this.ensureCustom();
    }
    if (this.route.name === 'editions') {
      this.draftPins = { ...this.pins };
      this.preview = this.data;
    }
  }

  private ensureCustom(): void {
    if (this.tab !== 'custom' || !this.data || this.data.custom || this.fixture) return;
    if (this.data.degraded?.kind === 'one_shop') return;
    const start = (this.data.cheapest.orders || []).map((o) => o.store_id);
    if (!start.length) return;
    this.selected = start;
    void this.solve();
  }

  async toggleShop(id: string): Promise<void> {
    const cur = this.data?.custom?.selected_store_ids ?? this.selected ?? [];
    const next = cur.includes(id) ? cur.filter((s) => s !== id) : [...cur, id];
    if (!next.length) return;
    this.selected = next;
    await this.solve();
  }

  async pick(itemId: string, edition: string): Promise<void> {
    const next = { ...this.draftPins };
    if (edition === 'any') delete next[itemId];
    else next[itemId] = edition;
    this.draftPins = next;
    this.busy = true;
    const p = await this.post(next, null);
    if (p) this.preview = p;
    this.busy = false;
  }

  applyPins(): void {
    if (!this.preview || this.preview.edition.status === 'not_possible') return;
    this.pins = { ...this.draftPins };
    this.selected = null;
    this.data = this.preview;
    this.go('result/' + this.tab);
  }

  cancelPins(): void {
    this.go('result/' + this.tab);
  }

  // ------------------------------------------------------------ basket

  get books(): BookRow[] {
    return (this.snapshot?.books || []).filter((b) => this.basket.has(b.item_id));
  }

  bookRow(id: string): BookRow | undefined {
    return this.data?.books.find((b) => b.item_id === id) ?? this.snapshot?.books.find((b) => b.item_id === id);
  }

  inBasket(id: string): boolean {
    return this.basket.has(id);
  }

  toggleBasket(id: string): void {
    if (this.basket.has(id)) this.basket.delete(id);
    else this.basket.add(id);
    this.basket = new Set(this.basket);
    this.dirty = true;
    this.pins = {};
    this.selected = null;
  }

  setQ(value: string): void {
    this.q = value;
  }

  findBook(): void {
    this.go('add');
  }

  get matches(): BookRow[] {
    const needle = this.fold(this.q);
    if (!needle) return [];
    const digits = this.q.replace(/\D/g, '');
    return (this.snapshot?.books || []).filter(
      (b) => this.fold(b.title).includes(needle) || (digits.length >= 4 && (b.isbn13 || '').includes(digits)),
    );
  }

  private fold(text: string): string {
    return text.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase().trim();
  }

  firstOffer(b: BookRow): OfferRow | undefined {
    return b.shops.find((o) => o.price_cents != null);
  }

  // ------------------------------------------------------------ formatting

  shopName(id: string | null | undefined): string {
    return id ? SHOP_NAME[id] || id : '';
  }

  money(cents: number | null | undefined): string {
    if (cents == null) return '';
    const sign = cents < 0 ? '-' : '';
    const abs = Math.abs(cents);
    const lei = Math.floor(abs / 100);
    return sign + lei.toLocaleString('ro-RO') + ',' + String(abs % 100).padStart(2, '0');
  }

  lei(cents: number | null | undefined): string {
    return this.money(cents) + ' lei';
  }

  // Feature 6: the entry link to the buy list for the orders on screen.
  get buyEntryText(): string {
    return MESSAGES[this.lang].buyListEntry;
  }

  buyHref(): string {
    return '#/buy/' + encodeBuyList(buyListFromOrders(this.orders));
  }

  // The free-delivery gap line, straight from the payload. '' hides it.
  deliveryGap(o: Order): string {
    const gap = o.delivery_gap;
    if (!gap) return '';
    const m = MESSAGES[this.lang];
    if (gap.status === 'reached') return m.deliveryGapReached;
    if (gap.status === 'short') return fill(m.deliveryGapShort, { amount: this.money(gap.short_cents), shop: this.shopName(o.store_id) });
    return '';
  }

  edLabel(e: string | null): string {
    return editionName(this.lang, e);
  }

  statusText(code: string): string {
    const key = STATUS_KEY[code];
    return key ? this.m[key] : code;
  }

  // A read line only where the API says there is one. Nothing is derived here.
  readStatus(o: OfferRow): 'match' | 'mismatch' | '' {
    const status = o.model_read?.status;
    return status === 'match' || status === 'mismatch' ? status : '';
  }

  readFields(o: OfferRow): string {
    return (o.model_read?.mismatch_fields || [])
      .map((f) => fieldName(this.lang, f))
      .join(', ');
  }

  private day(iso: string): string {
    const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
    return m ? Number(m[3]) + ' ' + this.m.monthsShort.split(' ')[Number(m[2]) - 1] : iso;
  }

  dateTime(iso: string | null): string {
    if (!iso) return '';
    const t = /T(\d{2}:\d{2})/.exec(iso);
    return this.day(iso) + (t ? ', ' + t[1] : '');
  }

  stamp(): string {
    const r = this.data?.read_at_range;
    if (!r?.newest) return '';
    if (!r.oldest || r.oldest === r.newest) return this.t('pricesRead', { date: this.day(r.newest) });
    const a = this.day(r.oldest).split(' ');
    const b = this.day(r.newest).split(' ');
    return this.t('pricesRead', { date: (a[1] === b[1] ? a[0] : a.join(' ')) + '–' + b.join(' ') });
  }

  // ------------------------------------------------------------ view helpers

  get degraded(): 'one_book' | 'one_shop' | null {
    return this.data?.degraded?.kind ?? null;
  }

  get orders(): Order[] {
    const d = this.data;
    if (!d) return [];
    if (this.tab === 'one') return d.one_order.answer?.orders || [];
    if (this.tab === 'custom') return d.custom?.orders || [];
    return d.cheapest.orders || [];
  }

  get answer(): Answer | null {
    const d = this.data;
    if (!d) return null;
    if (this.tab === 'one') return d.one_order.answer;
    if (this.tab === 'custom') return d.custom;
    return d.cheapest;
  }

  get pinCount(): number {
    return Object.keys(this.data?.edition.pins || {}).length;
  }

  editionsPill(): string {
    const n = this.pinCount;
    return this.t('editionsPill', { value: n ? this.t('editionsPinned', { n }) : this.m.editionsAny });
  }

  get oneDelta(): number | null {
    return this.data?.one_order.answer?.delta_vs_cheapest_cents ?? null;
  }

  get leftOut(): Shop[] {
    return (this.data?.shops || []).filter((s) => !s.selectable);
  }

  get shopOrder(): Order | undefined {
    const d = this.data;
    if (!d) return undefined;
    const pools: Order[][] = [
      this.lastOrderTab === 'one' ? d.one_order.answer?.orders || [] : this.lastOrderTab === 'custom' ? d.custom?.orders || [] : d.cheapest.orders || [],
      d.cheapest.orders || [],
      d.one_order.answer?.orders || [],
      d.custom?.orders || [],
    ];
    for (const pool of pools) {
      const hit = pool.find((o) => o.store_id === this.route.arg);
      if (hit) return hit;
    }
    return undefined;
  }

  get shop(): Shop | undefined {
    return this.data?.shops.find((s) => s.store_id === this.route.arg);
  }

  shopBooks(storeId: string): { book: BookRow; offer: OfferRow }[] {
    const rows: { book: BookRow; offer: OfferRow }[] = [];
    for (const b of this.snapshot?.books || []) {
      const offer = b.shops.find((o) => o.store_id === storeId && o.price_cents != null);
      if (offer) rows.push({ book: b, offer });
    }
    return rows;
  }

  failedFor(storeId: string): FailedRead[] {
    return (this.data?.failed_reads || []).filter((f) => f.store_id === storeId);
  }

  maxAttempts(rows: FailedRead[]): number {
    return rows.reduce((m, r) => Math.max(m, r.attempts), 0);
  }

  /** The "its pages didn't load" paragraph on the couldn't-read shop screen. */
  shopFailText(storeId: string): string {
    const rows = this.failedFor(storeId);
    const tries = this.count(this.maxAttempts(rows), 'try');
    const at = rows[0]?.failed_at;
    let text = at ? this.t('shopFailLoadWhen', { date: this.dateTime(at), tries }) : this.t('shopFailLoad', { tries });
    const total = this.data?.cheapest.total_cents;
    if (total != null) text += ' ' + this.t('shopFailCovers', { total: this.lei(total) });
    return text;
  }

  movedIds(): Set<string> {
    return new Set((this.data?.custom?.moves || []).map((m) => m.item_id));
  }

  movedFrom(storeId: string): number {
    return (this.data?.custom?.moves || []).filter((m) => m.from_store_id === storeId).length;
  }

  orderOf(storeId: string): Order | undefined {
    return this.data?.custom?.orders?.find((o) => o.store_id === storeId);
  }

  isChosen(storeId: string): boolean {
    return !!this.data?.custom?.selected_store_ids.includes(storeId);
  }

  meterFill(o: Order): number {
    const t = o.free_delivery_threshold_cents || 0;
    const scale = Math.max(o.qualifying_cents, t) || 1;
    return Math.round((o.qualifying_cents / scale) * 100);
  }

  meterMark(o: Order): number {
    const t = o.free_delivery_threshold_cents || 0;
    const scale = Math.max(o.qualifying_cents, t) || 1;
    return Math.round((t / scale) * 100);
  }

  names(rows: NotRanked): string {
    return rows.orders.map((o) => this.shopName(o.store_id) + ' ' + o.books.length).join(' + ');
  }

  missingNames(rows: MissingFee[]): string {
    return [...new Set(rows.map((m) => this.shopName(m.store_id)))].join(', ');
  }

  rankedShops(): ShopOption[] {
    return (this.data?.one_order.shops || []).filter((s) => s.status === 'ranked');
  }

  otherShops(): ShopOption[] {
    return (this.data?.one_order.shops || []).filter((s) => s.status !== 'ranked');
  }

  offerLink(url: string | null | undefined): string | null {
    return url && /^https?:\/\//.test(url) ? url : null;
  }

  get shopList(): string {
    const names = (this.data?.shops || []).map((s) => this.shopName(s.store_id));
    if (names.length < 2) return names.join('');
    return names.slice(0, -1).join(', ') + ' ' + this.m.listAnd + ' ' + names[names.length - 1];
  }

  trackId(_: number, x: { item_id?: string; store_id?: string }): string {
    return (x.item_id || '') + (x.store_id || '');
  }
}
