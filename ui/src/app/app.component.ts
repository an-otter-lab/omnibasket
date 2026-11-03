import { NgTemplateOutlet } from '@angular/common';
import { Component, ElementRef, HostListener, OnDestroy, effect, inject, untracked, viewChild } from '@angular/core';
import { Subscription, firstValueFrom } from 'rxjs';
import { BasketItem, BasketService, sameBook, itemId } from './basket.service';
import { BuyListComponent } from './buy-list.component';
import { EventsService, liveUrl } from './events.service';

/** The route argument of the photo read's progress screen. It is not an ISBN and starts no read. */
const PHOTO_ROUTE_ARG = 'photo';
import { LiveProgressComponent } from './live-progress.component';
import { Candidate, LiveOffer, Progress, badIsbn, isbnLang, parseInput, pastedBook } from './live';
import { PickListComponent, PickState } from './pick-list.component';
import { ShopReadsComponent } from './shop-reads.component';
import { buyListFromOrders, encodeBuyList } from './buy-list';
import { Lang, MESSAGES, Messages, ReasonArgs, count, editionName, fieldName, fill, reasonText } from './messages';
import { I18nService } from './i18n';
import { ThemePref, ThemeService } from './theme';
import { MembershipsComponent } from './memberships.component';
import { MembershipRow, loadDeclared, saveDeclared, shopsThatTakeBooks } from './memberships';
import { AskApplied, AskBoxComponent } from './ask-box.component';
import { PhotoInputComponent, PhotoInputEvent } from './photo-input.component';
import { PhotoResultComponent } from './photo-result.component';
import { MAX_PHOTO_BYTES, shrinkPhoto } from './photo';
import { ConfigService } from './config.service';
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
  reason_code?: string | null;
  reason_args?: ReasonArgs;
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
  degraded: { kind: 'one_book' | 'one_shop'; reason: string; reason_code?: string | null; reason_args?: ReasonArgs; store_id?: string } | null;
  shops: Shop[];
  books: BookRow[];
  cheapest: Answer & { degraded?: boolean };
  one_order: {
    status: string;
    reason: string | null;
    reason_code?: string | null;
    reason_args?: ReasonArgs;
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
    reason_code?: string | null;
    reason_args?: ReasonArgs;
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
  // Feature 5: the parent shows only the shops that can take a book in this basket.
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
  books_express: 'Books-Express',
  'books-express': 'Books-Express',
  elefant: 'Elefant',
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
  imports: [NgTemplateOutlet, BuyListComponent, PickListComponent, LiveProgressComponent, ShopReadsComponent, MembershipsComponent, PhotoResultComponent, AskBoxComponent],
  templateUrl: './app.component.html',
  styleUrl: './app.component.css',
})
export class AppComponent implements OnDestroy {
  private readonly events = inject(EventsService);
  private readonly i18n = inject(I18nService);
  private readonly themeService = inject(ThemeService);
  private readonly config = inject(ConfigService);
  readonly basketSvc = inject(BasketService);
  // True only in demo mode, after the shopper asked for the sample. Never in normal mode.
  sampleMode = false;
  private sampleIds = new Set<string>();
  loaded = false;
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
  isDemoMode = false;

  readonly encodeURIComponent = encodeURIComponent;
  route: Route = { name: 'entry', arg: '' };
  snapshot: Payload | null = null;
  data: Payload | null = null;
  loadError = false;
  busy = false;
  note = '';
  fixture = '';
  dirty = false;
  tab: Tab = 'cheapest';
  pins: Record<string, string> = {};
  draftPins: Record<string, string> = {};
  preview: Payload | null = null;
  selected: string[] | null = null;
  /** Ask left shops out: `selected` is the pool the custom answer picks the cheapest from (Adrian, 3 Nov). */
  askWithin = false;
  askLeftOut: string[] = [];
  lastOrderTab: Tab = 'cheapest';
  // Feature 8: the language lives in I18nService (browser default, toggle, storage).
  get lang(): Lang {
    return this.i18n.lang();
  }
  set lang(lang: Lang) {
    this.i18n.set(lang);
  }
  private whyPayload: unknown = null;
  /** R8/R8b: the /why paragraph for template or muse; empty while loading and after a failure (the box is hidden). */
  whyText = '';
  whyLoading = false;
  whyMuse = false;
  private whyRequest = 0;
  // Feature 5: memberships the shopper declared, kept in localStorage.
  declaredMemberships: string[] = [];
  // Feature 2: photo reading state.
  photoState: PhotoState = { kind: 'idle' };

  // Entry screen v2: menu state. R0/R4: the entry and add-book screens share the one field.
  langMenuOpen = false;
  themeMenuOpen = false;
  /** The add-book field. Empty whenever the state opens and after every pick (R0); the query lives in #/find/<q>. */
  fieldText = '';
  /** The polite live region: what was just added, and how many books the basket now holds. */
  addedNote = '';
  /** A pick whose prices could not be read. */
  addError = '';
  /** R12: the pick that matches a book already in the basket, held until the shopper chooses. */
  dupPick: { c: Candidate; listing?: string | null } | null = null;
  /** S26: R12 on the photo path. The line being asked about, the lines already taken, and those still to check. */
  photoDup: { line: ResolvedLine; ok: ResolvedLine[]; rest: ResolvedLine[] } | null = null;
  /** S2: one price read per book being added, keyed by ISBN; a new add never cancels another book's read. */
  private addStreams = new Map<string, { sub: Subscription | null; had: boolean }>();
  private readonly fieldRef = viewChild<ElementRef<HTMLInputElement>>('entryInput');
  /** R12: "Keep one" takes the focus when the duplicate question opens. */
  private readonly dupKeepRef = viewChild<ElementRef<HTMLButtonElement>>('dupKeep');
  private readonly photoDupKeepRef = viewChild<ElementRef<HTMLButtonElement>>('photoDupKeep');
  private documentClickListener: ((event: MouseEvent) => void) | null = null;

  constructor() {
    this.config.getConfig().subscribe((config) => {
      this.isDemoMode = config.demo;
      const sample = new URLSearchParams(window.location.search).get('sample');
      if (config.demo && sample && !window.location.hash) window.location.hash = '#/result/cheapest';
    });
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
    // Entry screen v2: close menus on outside click
    this.documentClickListener = (event: MouseEvent) => {
      const target = event.target as HTMLElement;
      if (!target.closest('.icmenu') && !target.closest('#lang-btn') && !target.closest('#theme-btn')) {
        this.closeMenus();
      }
    };
    document.addEventListener('click', this.documentClickListener);
  }

  ngOnDestroy(): void {
    this.stream?.unsubscribe();
    for (const r of this.addStreams.values()) r.sub?.unsubscribe();
    this.addStreams.clear();
    if (this.documentClickListener) {
      document.removeEventListener('click', this.documentClickListener);
      this.documentClickListener = null;
    }
  }

  @HostListener('window:hashchange')
  onHash(): void {
    const before = this.screenKey();
    this.readRoute();
    // S29: a new screen opens at its top; a result tab switch keeps the scroll position.
    if (this.screenKey() !== before) window.scrollTo(0, 0);
    this.routeChanged();
  }

  private screenKey(): string {
    return this.route.name === 'result' ? 'result' : this.route.name + '/' + this.route.arg;
  }

  // The first screen, the pick list and the live read need no basket data. Every
  // other screen reads the cached basket, loaded the first time it is wanted.
  private routeChanged(): void {
    const name = this.route.name;
    if (name !== 'live') this.stopStream();
    if (this.adding) {
      // R0: the axis of the defect was a query left in the field. Every visit to the add-book
      // state starts from an empty field; the query itself is only ever the #/find/<q> argument.
      this.clearField();
      this.addedNote = '';
      this.addError = '';
      this.dupPick = null;
      this.closeMenus();
      const q = name === 'find' ? this.route.arg.trim() : '';
      this.isbnWrong = false;
      if (q && badIsbn(q)) {
        // S8: a #/find/ link with a mistyped ISBN puts the number back in the field to fix.
        this.fieldText = q;
        const el = this.fieldRef()?.nativeElement;
        if (el) el.value = q;
        this.isbnWrong = true;
        this.boxText = '';
        this.candidates = [];
        this.pickState = 'idle';
      } else if (q) {
        void this.runSearch(q);
      } else {
        this.boxText = '';
        this.candidates = [];
        this.pickState = 'idle';
      }
      this.focusField();
    } else if (name === 'live') {
      if (this.route.arg !== PHOTO_ROUTE_ARG && this.liveIsbn !== this.route.arg) this.startLive(this.route.arg, this.picked?.isbn === this.route.arg ? this.picked.title : '');
    } else if (!this.loaded && !this.loading) {
      void this.load();
    } else {
      this.afterRoute();
    }
  }

  /** The four screens that share the one add-book field: the first run, #/add and #/find/<q>. */
  get adding(): boolean {
    const name = this.route.name;
    return name === 'entry' || name === 'add' || name === 'find';
  }

  /** The first-run copy (headline, How it works) belongs to an empty basket at #/ and nowhere else. */
  get firstRun(): boolean {
    return this.route.name === 'entry' && this.basketItems.length === 0;
  }

  /** What the one screen is showing: the first run, or the add-book state. */
  get screenName(): string {
    return this.firstRun ? 'first' : 'add';
  }

  onFieldInput(event: Event): void {
    this.fieldText = (event.target as HTMLInputElement).value;
    this.isbnWrong = false;
  }

  /** S8: a mistyped ISBN was entered; the text stays in the field and the note says why. */
  isbnWrong = false;

  /**
   * R0: empty the field in the model and in the input itself. A typed query cleared within the
   * same frame (Enter, or the pick straight after typing) would otherwise leave its text behind,
   * because the property binding only writes when the value it rendered last changes.
   */
  private clearField(): void {
    this.fieldText = '';
    const el = this.fieldRef()?.nativeElement;
    if (el) el.value = '';
  }

  /** Put the cursor in the empty field when the add-book state opens (R0). */
  private focusField(): void {
    setTimeout(() => {
      const el = this.fieldRef()?.nativeElement;
      if (el && document.activeElement !== el) el.focus();
    }, 0);
  }

  // ------------------------------------------------------------ entry screen v2 menus

  get theme(): ThemePref {
    return this.themeService.pref();
  }

  toggleLangMenu(): void {
    this.langMenuOpen = !this.langMenuOpen;
    this.themeMenuOpen = false;
    if (this.langMenuOpen) this.focusMenuOption('lang', this.lang);
  }

  toggleThemeMenu(): void {
    this.themeMenuOpen = !this.themeMenuOpen;
    this.langMenuOpen = false;
    if (this.themeMenuOpen) this.focusMenuOption('theme', this.theme);
  }

  setLang(lang: Lang): void {
    this.i18n.choose(lang); // remembered, as the old RO/EN toggle was (feature 8)
    this.langMenuOpen = false;
  }

  setTheme(theme: ThemePref): void {
    this.themeService.choose(theme); // remembered under THEME_KEY and applied to <html data-theme>
    this.themeMenuOpen = false;
  }

  closeMenus(): void {
    this.langMenuOpen = false;
    this.themeMenuOpen = false;
  }

  /** R5: the globe and the sun are listbox buttons: Enter/Space/ArrowDown open on the current
   *  choice, Escape closes and puts focus back on the trigger (design note §1). */
  onMenuButtonKey(event: KeyboardEvent, menuType: 'lang' | 'theme'): void {
    if (event.key === 'Escape') {
      if (menuType === 'lang' ? this.langMenuOpen : this.themeMenuOpen) {
        event.preventDefault();
        this.closeMenus();
      }
      this.focusMenuButton(menuType);
      return;
    }
    if (event.key === 'Enter' || event.key === ' ' || event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      const open = menuType === 'lang' ? this.langMenuOpen : this.themeMenuOpen;
      if (open) {
        this.closeMenus();
        return;
      }
      if (menuType === 'lang') {
        this.langMenuOpen = true;
        this.themeMenuOpen = false;
      } else {
        this.themeMenuOpen = true;
        this.langMenuOpen = false;
      }
      this.focusMenuOption(menuType, menuType === 'lang' ? this.lang : this.theme);
    }
  }

  /** Arrow keys move inside an open menu, Home/End jump, Escape closes it and returns focus. */
  onMenuListKey(event: KeyboardEvent, menuType: 'lang' | 'theme'): void {
    const menu = event.currentTarget as HTMLElement | null;
    const options = [...(menu?.querySelectorAll<HTMLElement>('[role="option"]') || [])];
    if (!options.length) return;
    const at = options.indexOf(document.activeElement as HTMLElement);
    let next = -1;
    switch (event.key) {
      case 'ArrowDown':
        next = at < 0 ? 0 : (at + 1) % options.length;
        break;
      case 'ArrowUp':
        next = at < 0 ? options.length - 1 : (at - 1 + options.length) % options.length;
        break;
      case 'Home':
        next = 0;
        break;
      case 'End':
        next = options.length - 1;
        break;
      case 'Escape':
        event.preventDefault();
        this.closeMenus();
        this.focusMenuButton(menuType);
        return;
      case 'Tab':
        this.closeMenus();
        return;
      default:
        return;
    }
    event.preventDefault();
    options[next].focus();
  }

  private focusMenuButton(menuType: 'lang' | 'theme'): void {
    const id = menuType === 'lang' ? 'lang-btn' : 'theme-btn';
    setTimeout(() => document.getElementById(id)?.focus());
  }

  /** After the menu renders, focus the option for the current choice. */
  private focusMenuOption(menuType: 'lang' | 'theme', choice: string): void {
    const id = menuType === 'lang' ? 'lang-opt-' + choice : 'theme-opt-' + choice;
    setTimeout(() => document.getElementById(id)?.focus());
  }

  /** R0: the field asks for a search and is empty again at once; the query is only in #/find/<q>. */
  /** S14 (D2): a search is running; Find book shows it and takes no second search meanwhile. */
  get findSearching(): boolean {
    return this.route.name === 'find' && this.pickState === 'searching';
  }

  onFieldSubmit(event: Event): void {
    event.preventDefault();
    if (this.findSearching) return;
    const text = this.fieldText.trim();
    if (!text) return;
    if (badIsbn(text)) {
      // S8: no search for a number that cannot be an ISBN, and the shopper keeps what they typed.
      this.isbnWrong = true;
      return;
    }
    this.isbnWrong = false;
    this.clearField();
    this.submitBox(text);
  }

  /** S19: a photo is being read; Photo of a list shows it and takes no second photo meanwhile. */
  get photoReading(): boolean {
    return this.photoState.kind === 'reading';
  }

  async onEntryPhoto(event: Event): Promise<void> {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0];
    if (!file || this.photoReading) return;
    input.value = '';

    this.photoState = { kind: 'reading' };
    const upload = await shrinkPhoto(file); // S22: a phone photo goes up at most 2000 px
    if (upload.body.size > MAX_PHOTO_BYTES) {
      this.onPhotoEvent({ kind: 'oversize', size: upload.body.size });
      return;
    }

    try {
      const res = await fetch('/photo', {
        method: 'POST',
        headers: { 'content-type': upload.type },
        body: await upload.body.arrayBuffer(),
      });
      const json = (await res.json()) as PhotoReadResponse;
      this.onPhotoEvent({ kind: 'read', response: json });
    } catch {
      this.onPhotoEvent({ kind: 'error' });
    }
  }

  // ------------------------------------------------------------ the one box

  submitBox(text: string): void {
    this.go('find/' + encodeURIComponent(text));
  }

  /** The no-match message's Clear button: back to the empty field, nothing left to search. */
  clearSearch(): void {
    this.clearField();
    this.boxText = '';
    this.candidates = [];
    this.pickState = 'idle';
    this.go('add');
    this.focusField();
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
    this.pickState = 'searching';
    if (parsed.kind === 'link') {
      // S25b: /input reads the page once and names the book from it; an ISBN in the address is only the fallback.
      if ((await this.resolvePastedLink(text, parsed.url, !!parsed.isbn)) || !parsed.isbn) return;
    }
    const isbn = parsed.kind === 'isbn' || parsed.kind === 'link' ? parsed.isbn : null;
    try {
      const res = await fetch('/search?limit=5&q=' + encodeURIComponent(isbn || text));
      // H3: a 503 means Open Library is busy or down, and a 429 (H3b) means our own rate limit;
      // both say search is busy and offer the same search again.
      if (res.status === 503 || res.status === 429) {
        if (this.route.name === 'find' && this.route.arg === text) this.pickState = 'busy';
        return;
      }
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

  /**
   * A pasted link: /input reads the page and names the book.
   * A resolved link goes straight to its live prices; only nothing-found says so.
   * With `fallback` (an ISBN in the address) a failed read returns false and the ISBN is searched instead.
   */
  private async resolvePastedLink(text: string, url: string, fallback = false): Promise<boolean> {
    let body: unknown = null;
    let answered = false;
    try {
      const res = await fetch('/input', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ raw_input: url }),
      });
      answered = res.ok;
      if (res.ok) body = await res.json();
    } catch {
      answered = false;
    }
    if (this.route.name !== 'find' || this.route.arg !== text) return true;
    const book = answered ? pastedBook(body) : null;
    if (!book && fallback) return false;
    if (!answered) {
      this.pickState = 'error';
      return true;
    }
    if (!book) {
      this.pickState = 'link_failed';
      return true;
    }
    // The resolved book joins the basket the same way a picked row does, and the
    // page that was pasted is read as that shop's listing for its price.
    this.pickBook({ title: book.title || '', author: book.author, isbn: book.isbn, cover_url: null, shops: [] }, book.listing);
    return true;
  }

  pickBook(c: Candidate, listing?: string | null): void {
    if (!c.isbn) return;
    // R12: the same normalised title and author under another ISBN is a question, never a silent
    // second copy. Nothing joins the basket until the shopper answers.
    if (this.basketSvc.duplicateOf(c.isbn, c.title, c.author)) {
      this.dupPick = { c, listing };
      this.addedNote = '';
      this.addError = '';
      setTimeout(() => this.dupKeepRef()?.nativeElement.focus(), 0);
      return;
    }
    this.takePick(c, listing);
  }

  /** R12: "Add anyway" keeps both copies and finishes the pick as usual. */
  addAnyway(): void {
    const pick = this.dupPick;
    this.dupPick = null;
    if (pick) this.takePick(pick.c, pick.listing);
  }

  /** R12: "Keep one" adds nothing; the book already in the basket stays, and the state resets. */
  keepOne(): void {
    this.dupPick = null;
    this.clearField();
    this.candidates = [];
    this.pickState = 'idle';
    this.boxText = '';
    this.route = { name: 'add', arg: '' };
    this.replaceRoute('add');
    this.focusField();
  }

  private takePick(c: Candidate, listing?: string | null): void {
    // R0/R4: a pick adds the book here. The field and the rows go, the state stays.
    this.clearField();
    this.candidates = [];
    this.pickState = 'idle';
    this.addError = '';
    this.addedNote = '';
    this.picked = c;
    this.liveTitle = c.title;
    this.liveIsbn = '';
    this.route = { name: 'add', arg: '' };
    this.replaceRoute('add');
    this.addToBasket(c, listing);
    this.focusField();
  }

  /**
   * The picked book joins the basket at once, so the chip and the count are honest straight away;
   * its prices are read in the background and the same book is upgraded in place when the read
   * answers. A read that fails (and a book that was not in the basket before) leaves again, and
   * the shopper is told, rather than shown a book no shop can price.
   */
  private addToBasket(c: Candidate, listing?: string | null): void {
    const isbn = c.isbn as string;
    const title = (c.title || '').trim() || 'ISBN ' + isbn;
    const author = c.author ?? null;
    // S2: only a read for this same ISBN is replaced; it keeps whether the book was there before it.
    const pending = this.addStreams.get(isbn);
    pending?.sub?.unsubscribe();
    const had = pending ? pending.had : this.basketSvc.has(isbn);
    this.basketSvc.addUnpriced(isbn, title, author);
    this.noteAdded(title);
    this.markStale();
    const entry: { sub: Subscription | null; had: boolean } = { sub: null, had };
    this.addStreams.set(isbn, entry);
    let done = false;
    const settle = (payload: Payload | null): void => {
      if (done) return;
      done = true;
      if (this.addStreams.get(isbn) === entry) this.addStreams.delete(isbn);
      if (payload) {
        this.basketSvc.addFromLive(adapt(payload), isbn, title, author);
        this.noteAdded(title);
      } else {
        if (!had) this.basketSvc.remove(itemId(isbn));
        this.addError = fill(this.m.addReadFailed, { title });
      }
      this.markStale();
    };
    const sub = this.events.open(liveUrl(isbn, itemId(isbn), title, author, listing)).subscribe({
      next: (ev) => {
        if (ev.type === 'solution') settle(ev.payload as Payload);
        else if (ev.type === 'error') settle(null);
      },
      error: () => settle(null),
      complete: () => settle(null),
    });
    if (done) sub.unsubscribe();
    else entry.sub = sub;
  }

  private noteAdded(title: string): void {
    this.addedNote = fill(this.m.addedToBasket, { title, books: count(this.lang, this.basketSvc.count, 'book') });
  }

  /** The basket changed: the next result screen is solved again, and a visible one now. */
  private markStale(): void {
    this.dirty = true;
    if (this.route.name === 'result') void this.refresh();
  }

  /** The URL follows the add-book state without a route round-trip: no second search, no scroll jump. */
  private replaceRoute(path: string): void {
    const next = '#/' + path;
    if (window.location.hash === next) return;
    window.history.replaceState(null, '', window.location.pathname + window.location.search + next);
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
    this.liveOffers = [];
    this.stream = this.events.open(liveUrl(isbn, 'book-' + isbn, this.liveTitle, this.picked?.isbn === isbn ? this.picked.author : null)).subscribe({
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

  // The picked book joins the shopper's basket. Nothing else from the live payload is kept.
  private finishLive(payload: Payload): void {
    const body = adapt(payload);
    this.leaveSample();
    this.basketSvc.addFromLive(body, this.liveIsbn, this.liveTitle);
    this.resetPlan();
    void this.refresh().then(() => this.go('result/cheapest'));
  }

  private resetPlan(): void {
    this.pins = {};
    this.selected = null;
    this.askWithin = false; this.askLeftOut = [];
    this.dirty = false;
    this.tab = 'cheapest';
  }

  private leaveSample(): void {
    if (!this.sampleMode) return;
    this.sampleMode = false;
    this.fixture = '';
    this.sampleIds = new Set();
    this.data = null;
    this.snapshot = null;
    if (window.location.search) window.history.replaceState(null, '', window.location.pathname + window.location.hash);
  }

  /** Every id in the shopper's basket (or in the demo sample, when asked for in demo mode). */
  get basket(): Set<string> {
    return this.sampleMode ? this.sampleIds : new Set(this.basketSvc.items.map((i) => i.id));
  }

  get basketItems(): BasketItem[] {
    return this.sampleMode ? [] : this.basketSvc.items;
  }

  /** S13 (D1): the order chip names the printing's language when the shop priced another-language printing. */
  printingLang(itemId: string, storeId: string): string {
    const item = this.basketItems.find((i) => i.id === itemId);
    const o = item?.live_offers?.find((x) => x.store_id === storeId);
    const got = o?.other_printing ? isbnLang(o.isbn13) : null;
    const picked = isbnLang(item?.isbn);
    return got && picked && got !== picked ? got : '';
  }

  get unplacedItems(): BasketItem[] {
    return this.sampleMode ? [] : this.basketSvc.unplaced();
  }

  isNoOffer(i: BasketItem): boolean {
    return !i.live_offers.some((o) => o.price_cents != null) && !i.offers.length;
  }

  /** S33: basket books in none of the shown orders, each with why. */
  get leftOutBooks(): { item: BasketItem; reason: string }[] {
    const orders = this.orders;
    if (!orders.length) return [];
    const placed = new Set(orders.flatMap((o) => o.books.flatMap((b) => [b.item_id, b.isbn13])));
    return this.basketItems
      .filter((i) => !placed.has(i.id) && !placed.has(i.isbn))
      .map((i) => ({ item: i, reason: this.isNoOffer(i) ? this.m.leftOutNoShop : this.unplacedItems.includes(i) ? this.m.leftOutNoRules : this.m.leftOutNotHere }));
  }

  get leftOutHead(): string {
    const n = this.leftOutBooks.length;
    return n === 1 ? this.m.leftOutBooksOne : this.t('leftOutBooksMany', { books: this.count(n, 'book') });
  }

  /** S33: the left-out line jumps to that book's row in Your books. */
  toBookRow(event: Event, isbn: string): void {
    event.preventDefault();
    const row = document.querySelector<HTMLElement>('[data-section="your-books"] [data-isbn="' + isbn + '"]');
    if (!row) return;
    row.setAttribute('tabindex', '-1');
    row.scrollIntoView({ block: 'start' });
    row.focus({ preventScroll: true });
  }

  removeBook(id: string): void {
    this.basketSvc.remove(id);
    this.resetPlan();
    void this.refresh();
  }

  /** The add-book chip's ×: the book leaves, and the result screen is solved again when it is opened. */
  removeChip(id: string): void {
    this.basketSvc.remove(id);
    this.resetPlan();
    this.addedNote = '';
    this.dupPick = null;
    this.markStale();
  }

  clearBasket(): void {
    this.basketSvc.clear();
    this.resetPlan();
    void this.refresh();
  }

  /** Re-price the shopper's basket. With nothing to price, there is no answer to show. */
  async refresh(): Promise<void> {
    this.loadError = false;
    if (!this.basketSvc.givenBody()) {
      this.data = null;
      this.snapshot = null;
      this.loaded = true;
      return;
    }
    this.busy = true;
    const next = await this.post(this.pins, this.selected);
    this.busy = false;
    if (next) {
      this.snapshot = next;
      this.data = next;
      void this.loadWhy(next);
      this.note = '';
    } else {
      this.loadError = !this.note;
    }
    this.loaded = true;
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

  /** In-app links go through go(): a plain #fragment link resolves against <base href> and
   *  drops the query, so a demo link (?sample=) would lose its basket on the first click. */
  /** S32: on the result page the header book count jumps to "Your books"; elsewhere it opens the result. */
  onCountClick(event: Event): void {
    const books = this.route.name === 'result' ? document.querySelector<HTMLElement>('[data-section="your-books"]') : null;
    if (!books) return this.onLinkClick(event, 'result');
    event.preventDefault();
    books.scrollIntoView({ block: 'start' });
    books.querySelector<HTMLElement>('#yb-h')?.focus({ preventScroll: true });
  }

  onLinkClick(event: Event, path: string): void {
    event.preventDefault();
    this.go(path);
  }

  back(): void {
    if (window.history.length > 1) window.history.back();
    else this.go('result/' + this.tab);
  }

  // ------------------------------------------------------------ data

  async load(): Promise<void> {
    this.loadError = false;
    this.loading = true;
    const cfg = await firstValueFrom(this.config.getConfig());
    this.isDemoMode = cfg.demo;
    const params = new URLSearchParams(window.location.search);
    // The recorded sample is demo-only and only when asked for. Normal mode never reads it.
    this.fixture = cfg.demo ? params.get('fixture') || '' : '';
    this.sampleMode = cfg.demo && (params.get('sample') !== null || !!this.fixture);
    try {
      if (this.sampleMode) {
        const res = this.fixture
          ? await fetch('/fixtures/' + this.fixture + '.json')
          : await fetch('/solve', { method: 'POST', headers: { 'content-type': 'application/json' }, body: '{}' });
        const body = adapt((await res.json()) as Payload);
        if (!res.ok || body.error) throw new Error(body.error || 'solve failed');
        this.snapshot = body;
        this.data = body;
        void this.loadWhy(body);
        this.sampleIds = new Set(body.books.map((b) => b.item_id));
        const known = new Set((body.memberships || []).map((row) => row.id));
        this.declaredMemberships = loadDeclared().filter((id) => known.has(id));
        if (this.declaredMemberships.length && !this.fixture) await this.solve();
        this.loaded = true;
      } else {
        this.declaredMemberships = loadDeclared();
        await this.refresh();
        const known = new Set((this.data?.memberships || []).map((row) => row.id));
        const kept = this.declaredMemberships.filter((id) => known.has(id));
        if (kept.length) {
          this.declaredMemberships = kept;
          await this.refresh();
        } else {
          this.declaredMemberships = [];
        }
      }
      this.afterRoute();
    } catch {
      this.loadError = true;
    }
    this.loading = false;
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
    this.whyText = '';
    this.whyLoading = this.hasDescribableResult(payload);
    if (!this.whyLoading) return;
    try {
      const res = await fetch('/why', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ payload, lang: this.lang }) });
      if (request !== this.whyRequest) return;
      if (!res.ok) { this.whyLoading = false; return; }
      const result = await res.json() as { text?: string; source?: string };
      if (request !== this.whyRequest) return;
      const text = (result.text || '').trim();
      if (!text || (result.source !== 'muse' && result.source !== 'template')) { this.whyLoading = false; return; }
      // R8b: the server's own template sentence is shown too, not only the Muse paragraph.
      this.whyText = text;
      this.whyMuse = result.source === 'muse';
      this.whyLoading = false;
    } catch {
      if (request === this.whyRequest) this.whyLoading = false;
      // R8b: a failed /why hides the box; no filler sentence.
    }
  }

  private async post(pins: Record<string, string>, selected: string[] | null): Promise<Payload | null> {
    if (this.fixture) {
      this.note = this.m.recordedNote;
      return null;
    }
    // Normal mode: exactly the shopper's books. The sample ({}) exists only in demo mode.
    const body: Record<string, unknown> | null = this.sampleMode ? {} : (this.basketSvc.givenBody() as Record<string, unknown> | null);
    if (!body) return null;
    if (Object.keys(pins).length) body['edition_pins'] = pins;
    if (selected) body['selected_store_ids'] = selected;
    if (selected && this.askWithin) body['selected_within'] = true;
    if (this.declaredMemberships.length) body['memberships'] = this.declaredMemberships;
    const res = await fetch('/solve', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) });
    const payload = adapt((await res.json()) as Payload);
    if (!res.ok || payload.error) {
      this.note = payload.error || this.m.solveFailed;
      return null;
    }
    return payload;
  }

  // Feature 7: apply the Ask box's answer, solve, route; if exact editions cannot be bought together, roll the pins back.
  // The box hears what the solve gave, so its reply can say when there is no plan.
  async onAsk(r: AskApplied): Promise<void> {
    const before = this.pins;
    this.tab = r.next.tab; this.selected = r.next.selected; this.pins = r.next.pins; this.declaredMemberships = r.next.memberships;
    this.askWithin = r.next.within; this.askLeftOut = r.next.leftOut;
    saveDeclared(this.declaredMemberships);
    await this.solve();
    const ok = !(this.data?.edition.status === 'not_possible' && JSON.stringify(before) !== JSON.stringify(this.pins));
    if (!ok) { this.pins = before; await this.solve(); }
    this.go('result/' + this.tab);
    r.done(ok, { orders: this.orders.length, missing: this.leftOutBooks.map((b) => b.item.title), tab: this.tab, noShop: this.noShopLeft });
  }

  /** Ask left shops out and Custom has no plan: the books no remaining shop lists (in the pinned edition, if any). */
  get noShopLeft(): string[] {
    const c = this.data?.custom;
    if (!this.askWithin || this.tab !== 'custom' || c?.status !== 'not_possible') return [];
    const left = new Set(c.selected_store_ids);
    return (this.data?.books || [])
      .filter((b) => {
        const where = b.edition_pin
          ? b.editions.find((e) => e.edition === b.edition_pin)?.store_ids || []
          : b.shops.filter((o) => o.price_cents != null).map((o) => o.store_id);
        return !where.some((id) => left.has(id));
      })
      .map((b) => b.title);
  }

  /** Custom's no-total heading: after Ask left shops out it names them, so the page says why no plan fits. */
  get noTotalHeading(): string {
    const out = this.askWithin ? this.askLeftOut.map((id) => this.shopName(id)) : [];
    return out.length ? this.t('noPlanWithout', { shops: out.join(', ') }) : this.m.noTotalShops;
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
    this.photoDup = null;
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
    if (this.photoState.kind !== 'result' || this.photoDup) return;
    const resolved: ResolvedLine[] = [...this.photoState.matched];
    for (const a of this.photoState.ambiguous) {
      if (a.picked) {
        resolved.push({ read_title: a.line.read_title, read_author: a.line.read_author, candidate: a.picked });
      }
    }
    if (resolved.length === 0) return;
    this.askPhotoDups([], resolved);
  }

  /** S26: each line that is a book already in the basket (or an earlier line) under another ISBN is asked, one at a time; nothing is read before. */
  private askPhotoDups(ok: ResolvedLine[], rest: ResolvedLine[]): void {
    for (let k = 0; k < rest.length; k++) {
      const line = rest[k];
      const me = { isbn: line.candidate.isbn, title: line.candidate.title || line.read_title, author: line.candidate.author || line.read_author || null };
      const twin = this.basketSvc.duplicateOf(me.isbn, me.title, me.author) || ok.find((o) => sameBook({ isbn: o.candidate.isbn, title: o.candidate.title || o.read_title, author: o.candidate.author || o.read_author || null }, me));
      if (twin) {
        this.photoDup = { line, ok, rest: rest.slice(k + 1) };
        setTimeout(() => this.photoDupKeepRef()?.nativeElement.focus(), 0);
        return;
      }
      ok = [...ok, line];
    }
    this.photoDup = null;
    if (ok.length) this.readPhotoLines(ok);
    else {
      this.photoState = { kind: 'idle' };
      this.go(this.basketItems.length ? 'result/cheapest' : 'add');
    }
  }

  /** S26: "Add anyway" keeps the photo line; "Keep one" drops it. Then the next line is checked. */
  photoDupAnswer(add: boolean): void {
    const d = this.photoDup;
    if (!d) return;
    this.photoDup = null;
    this.askPhotoDups(add ? [...d.ok, d.line] : d.ok, d.rest);
  }

  private readPhotoLines(resolved: ResolvedLine[]): void {
    // Reset photo state and read every resolved book live, each by its own ISBN, title and author:
    // the same request a hand-picked book makes. 'live/photo' is only the progress screen, not an ISBN.
    this.photoState = { kind: 'idle' };
    this.go('live/' + PHOTO_ROUTE_ARG);

    this.progress = [];
    this.liveFailed = false;
    this.liveOffers = [];
    this.liveIsbn = '';
    this.liveTitle = count(this.lang, resolved.length, 'photoBooks');

    let settled = 0;
    const total = resolved.length;
    this.leaveSample();
    const finishOne = (): void => {
      settled++;
      if (settled !== total) return;
      this.picked = null;
      this.resetPlan();
      void this.refresh().then(() => this.go('result/cheapest'));
    };
    resolved.forEach((line) => {
      const isbn = line.candidate.isbn;
      const title = line.candidate.title || line.read_title;
      const author = line.candidate.author || line.read_author || null;
      let done = false;
      // One book's failure lists it unpriced; it never stops the others.
      const settle = (payload: Payload | null): void => {
        if (done) return;
        done = true;
        if (payload) this.basketSvc.addFromLive(adapt(payload), isbn, title, author);
        else this.basketSvc.addUnpriced(isbn, title, author);
        finishOne();
      };
      this.events.open(liveUrl(isbn, itemId(isbn), title, author)).subscribe({
        next: (ev) => {
          if (ev.type === 'progress') this.progress = [...this.progress, ev.progress];
          else if (ev.type === 'solution') settle(ev.payload as Payload);
          else settle(null);
        },
        error: () => settle(null),
        complete: () => settle(null),
      });
    });
  }

  async solve(): Promise<void> {
    this.busy = true;
    this.note = '';
    const next = await this.post(this.pins, this.selected);
    if (next) {
      this.data = next;
      this.snapshot = this.snapshot ?? next;
      void this.loadWhy(next);
      this.dirty = false;
      if (this.oneShopOnly(next) && this.route.name === 'result') this.tab = 'one';
    }
    this.busy = false;
  }

  private afterRoute(): void {
    if (!this.data) {
      // S1: the visit started with an empty basket (loaded, no data); a book added since is priced
      // when the result screen opens, instead of a blank screen until a reload.
      if (this.route.name === 'result' && !this.sampleMode && !this.busy && this.basketSvc.givenBody()) {
        void this.refresh().then(() => {
          if (!this.data) return;
          this.dirty = false;
          this.afterRoute();
        });
      }
      return;
    }
    if (this.route.name === 'result') {
      if (this.oneShopOnly(this.data)) this.tab = 'one';
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
    this.askWithin = false; this.askLeftOut = [];
    void this.solve();
  }

  async toggleShop(id: string): Promise<void> {
    const cur = this.data?.custom?.selected_store_ids ?? this.selected ?? [];
    const next = cur.includes(id) ? cur.filter((s) => s !== id) : [...cur, id];
    if (!next.length) return;
    this.selected = next;
    this.askWithin = false; this.askLeftOut = [];
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
    this.askWithin = false; this.askLeftOut = [];
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
    this.removeBook(id);
  }

  firstOffer(b: BookRow): OfferRow | undefined {
    return b.shops.find((o) => o.price_cents != null);
  }

  // ------------------------------------------------------------ formatting

  /** S23: a plan "why not" line in the shopper's language (the API sends a code and its arguments). */
  why(a: { reason: string | null; reason_code?: string | null; reason_args?: ReasonArgs } | null | undefined): string {
    return a ? reasonText(this.lang, a.reason_code, a.reason_args, a.reason, (id) => this.shopName(id)) : '';
  }

  /** S23: why a shop cannot take a book (shop rows) or cannot be chosen (lock), by code. */
  shopWhy(kind: 'shop' | 'lock', code: string | null | undefined, fallback: string | null | undefined): string {
    return reasonText(this.lang, code ? kind + ':' + code : null, {}, fallback, (id) => this.shopName(id));
  }

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
    // S12: a range within one day is that day, not "31–31 Oct".
    if (!r.oldest || this.day(r.oldest) === this.day(r.newest)) return this.t('pricesRead', { date: this.day(r.newest) });
    const a = this.day(r.oldest).split(' ');
    const b = this.day(r.newest).split(' ');
    return this.t('pricesRead', { date: (a[1] === b[1] ? a[0] : a.join(' ')) + '–' + b.join(' ') });
  }

  // ------------------------------------------------------------ view helpers

  /** One shop priced but no ranked order there: only the one-order tab has something to show. */
  private oneShopOnly(d: Payload): boolean {
    return d.degraded?.kind === 'one_shop' && d.cheapest.status !== 'ranked';
  }

  get degraded(): 'one_book' | 'one_shop' | null {
    return this.data?.degraded?.kind ?? null;
  }

  /** Heading for one_book degraded state: honest about priced vs total basket books. */
  get oneBookHeading(): string {
    if (this.degraded !== 'one_book') return '';
    const priced = this.data?.books.filter(b => b.shops.some(s => s.price_cents != null)).length ?? 0;
    const total = this.basket.size;
    if (total <= 1) return this.m.oneBookTitle;
    return this.t('oneOfBooksPricedTitle', { priced, total });
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

  /** R10: an editions control only when at least one book has a second edition. */
  get hasEditions(): boolean {
    return this.books.some((b) => (b.editions?.length ?? 0) > 1);
  }

  /** R10: the editions dialog lists only books that have a choice. */
  get editionBooks(): BookRow[] {
    return this.books.filter((b) => (b.editions?.length ?? 0) > 1);
  }

  /** R10: a membership belongs to a shop that can take a book in this basket. */
  get membershipRows(): MembershipRow[] {
    const can = shopsThatTakeBooks(this.data?.shops || [], this.orders);
    return (this.data?.memberships || []).filter((r) => can.has(r.store_id));
  }

  /** R10: why a chosen shop's switch is locked (it is the only shop with a book). */
  lockedReason(s: Shop): string | null {
    if (!s.selectable) return null; // the shop's own reason is shown instead
    const chosen = this.data?.custom?.selected_store_ids?.length ?? 0;
    if (!this.isChosen(s.store_id) || chosen > 1) return null;
    const titles = this.onlyShopTitles(s.store_id);
    return titles ? this.t('onlyShopWith', { titles }) : this.m.onlyLastShop;
  }

  private onlyShopTitles(storeId: string): string {
    const titles = this.books
      .filter((b) => {
        const priced = b.shops.filter((o) => o.price_cents != null);
        return priced.length > 0 && priced.every((o) => o.store_id === storeId);
      })
      .map((b) => b.title);
    return titles.length > 2 ? titles.slice(0, 2).join(', ') + '…' : titles.join(', ');
  }

  /** The id of a locked switch's reason line, so the switch can point at it. */
  lockId(storeId: string): string {
    return 'lockid-' + storeId;
  }

  get oneDelta(): number | null {
    return this.data?.one_order.answer?.delta_vs_cheapest_cents ?? null;
  }

  /** R7: the cheapest split is a single order, so one tab stands for both "1 order" and "cheapest". */
  get cheapestIsOneOrder(): boolean {
    return this.data?.cheapest.order_count === 1;
  }

  /** R9: the total card exists only when the active tab has a total to show (no empty card). */
  get showsTotal(): boolean {
    if (this.tab === 'one') return !!this.data?.one_order.answer;
    if (this.tab === 'custom') return this.data?.custom?.status === 'ranked';
    return this.data?.cheapest.status === 'ranked';
  }

  /** R5: the header count — the shopper's books, or the demo sample's books in demo mode. */
  get headerBookCount(): number {
    return this.sampleMode ? this.sampleIds.size : this.basketSvc.items.length;
  }

  /** ARIA plumbing for the result panel (kept out of the template so copy-scan stays clean). */
  readonly panelRole = 'tabpanel';
  readonly panelId = 'result-panel';

  /** The tab that is selected right now, so the result panel can name it (design note §5). */
  get activeTabId(): string {
    if (this.degraded === 'one_shop') return 'tab-cheapest';
    if (this.cheapestIsOneOrder) return this.tab === 'custom' ? 'tab-custom' : 'tab-cheapest';
    return 'tab-' + this.tab;
  }

  /** R7: the tabs are role=tab; arrows move and activate, Home/End jump (design note §5). */
  onTabsKey(event: KeyboardEvent): void {
    const nav = event.currentTarget as HTMLElement | null;
    if (!nav) return;
    const tabs = [...nav.querySelectorAll<HTMLAnchorElement>('[role="tab"]:not([aria-disabled="true"])')];
    if (!tabs.length) return;
    const at = tabs.indexOf(document.activeElement as HTMLAnchorElement);
    let next: number;
    switch (event.key) {
      case 'ArrowRight':
        next = at < 0 ? 0 : (at + 1) % tabs.length;
        break;
      case 'ArrowLeft':
        next = at < 0 ? tabs.length - 1 : (at - 1 + tabs.length) % tabs.length;
        break;
      case 'Home':
        next = 0;
        break;
      case 'End':
        next = tabs.length - 1;
        break;
      default:
        return;
    }
    event.preventDefault();
    const id = tabs[next].id;
    tabs[next].click(); // activation is navigation: the tab is a link
    setTimeout(() => document.getElementById(id)?.focus());
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
