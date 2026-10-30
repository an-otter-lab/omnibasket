import { Component, Input } from '@angular/core';
import {
  BUY_SHOP_NAME,
  BuyBook,
  BuyShop,
  decodeBuyList,
  formatLei,
  librisCartUrl,
  safeListingUrl,
  storageKey,
} from './buy-list';
import { Lang, MESSAGES, Messages, fill } from './messages';

interface Step {
  title: string;
  store_id: string;
  url: string;
}

interface Saved {
  ticks: string[];
  opened: number;
}

// Feature 6: buy list per shop, at #/buy/<code>. Standalone: everything it
// shows comes from the code in its own link.
@Component({
  selector: 'app-buy-list',
  standalone: true,
  styles: [
    '.tick{width:22px;height:22px;flex:none;accent-color:#14532d;margin-right:10px}',
    '.rowlink{display:flex;align-items:center;gap:6px;flex-wrap:wrap;cursor:pointer}',
    '.rowr{display:flex;gap:6px;flex-wrap:wrap}',
    '.shareurl{width:100%;margin:8px 0}',
  ],
  template: `
    <header class="hdr"><a class="lnk" href="#/result">‹ {{ m.buyListBack }}</a></header>
    <main class="wrap narrow buylist">
      <h1 class="h2">{{ m.buyListTitle }}</h1>
      @if (shops) {
        <p class="s">{{ m.buyListIntro }}</p>

        @if (steps.length) {
          <div class="box stepper">
            <p class="s n opened" role="status">{{ openedText }}</p>
            @if (opened < steps.length) {
              <button class="btn full opennext" type="button" (click)="openNext()">{{ nextText }}</button>
            } @else {
              <p class="s ink">{{ m.buyListAllOpened }}</p>
              <button class="btn2" type="button" (click)="startAgain()">{{ m.buyListStartAgain }}</button>
            }
            <p class="s">{{ m.buyListStepperNote }}</p>
          </div>
        }

        @for (s of shops; track s.store_id; let si = $index) {
          <section class="obox on shoplist" [attr.data-shop]="s.store_id">
            <div class="phead"><h2 class="pt">{{ orderTitle(s.store_id) }}</h2></div>
            @for (b of s.books; track $index; let bi = $index) {
              <div class="row">
                <label class="rowlink">
                  <input type="checkbox" class="tick" [checked]="isTicked(s.store_id, bi)" (change)="toggle(s.store_id, bi)" [attr.aria-label]="tickLabel(b)" />
                  <span class="bt">{{ b.title }}</span>
                  @if (b.price_cents != null) { <span class="s n price">{{ lei(b.price_cents) }}</span> }
                </label>
                <span class="rowr">
                  @if (listing(s.store_id, b); as href) {
                    <a class="store listing" [href]="href" target="_blank" rel="noopener" [attr.aria-label]="openLabel(b, s.store_id)">{{ m.buyListOpen }}</a>
                  } @else {
                    <span class="unk">{{ m.buyListNoLink }}</span>
                  }
                  @if (cart(s.store_id, b); as cartHref) {
                    <a class="store cartadd" [href]="cartHref" target="_blank" rel="noopener" [attr.aria-label]="cartLabel(b)">{{ m.buyListLibrisCart }}</a>
                  }
                </span>
              </div>
            }
            @if (s.store_id === 'libris' && hasCart(s)) { <p class="s">{{ m.buyListLibrisCartNote }}</p> }
          </section>
        }

        <div class="box share">
          <button class="btn2" type="button" (click)="copy()">{{ copied ? m.buyListCopied : m.buyListShare }}</button>
          <input class="inp shareurl" readonly [value]="shareUrl" [attr.aria-label]="m.buyListShareLabel" />
          <p class="s">{{ m.buyListShareHint }}</p>
        </div>
      } @else {
        <p class="p">{{ m.buyListInvalid }}</p>
      }
    </main>
  `,
})
export class BuyListComponent {
  @Input() lang: Lang = 'en';

  shops: BuyShop[] | null = null;
  steps: Step[] = [];
  opened = 0;
  copied = false;
  private ticks = new Set<string>();
  private key = '';
  private codeValue = '';

  @Input() set code(value: string) {
    this.codeValue = value || '';
    this.shops = decodeBuyList(this.codeValue);
    this.key = storageKey(this.codeValue);
    this.steps = [];
    for (const s of this.shops || []) {
      for (const b of s.books) {
        const url = safeListingUrl(s.store_id, b.listing_url);
        if (url) this.steps.push({ title: b.title, store_id: s.store_id, url });
      }
    }
    const saved = this.load();
    this.ticks = new Set(saved.ticks);
    this.opened = Math.min(Math.max(0, saved.opened), this.steps.length);
    this.copied = false;
  }

  get code(): string {
    return this.codeValue;
  }

  get m(): Messages {
    return MESSAGES[this.lang] || MESSAGES.en;
  }

  get shareUrl(): string {
    return window.location.origin + window.location.pathname + '#/buy/' + this.codeValue;
  }

  get openedText(): string {
    return fill(this.m.buyListOpenedCount, { opened: String(this.opened), total: String(this.steps.length) });
  }

  get nextText(): string {
    const step = this.steps[this.opened];
    return step ? fill(this.m.buyListOpenNext, { title: step.title, shop: this.shopName(step.store_id) }) : '';
  }

  shopName(id: string): string {
    return BUY_SHOP_NAME[id] || id;
  }

  orderTitle(id: string): string {
    return fill(this.m.buyListOrder, { shop: this.shopName(id) });
  }

  lei(cents: number | null): string {
    return formatLei(cents) + ' lei';
  }

  listing(storeId: string, b: BuyBook): string | null {
    return safeListingUrl(storeId, b.listing_url);
  }

  cart(storeId: string, b: BuyBook): string | null {
    return librisCartUrl(storeId, b.listing_url);
  }

  hasCart(s: BuyShop): boolean {
    return s.books.some((b) => this.cart(s.store_id, b));
  }

  tickLabel(b: BuyBook): string {
    return fill(this.m.buyListTickLabel, { title: b.title });
  }

  openLabel(b: BuyBook, storeId: string): string {
    return fill(this.m.buyListOpenLabel, { title: b.title, shop: this.shopName(storeId) });
  }

  cartLabel(b: BuyBook): string {
    return fill(this.m.buyListLibrisCartLabel, { title: b.title });
  }

  isTicked(storeId: string, index: number): boolean {
    return this.ticks.has(storeId + '/' + index);
  }

  toggle(storeId: string, index: number): void {
    const id = storeId + '/' + index;
    if (this.ticks.has(id)) this.ticks.delete(id);
    else this.ticks.add(id);
    this.save();
  }

  /** Exactly one window.open per tap: each tap is its own user gesture. */
  openNext(): void {
    const step = this.steps[this.opened];
    if (!step) return;
    window.open(step.url, '_blank', 'noopener');
    this.opened += 1;
    this.save();
  }

  startAgain(): void {
    this.opened = 0;
    this.save();
  }

  async copy(): Promise<void> {
    try {
      await navigator.clipboard.writeText(this.shareUrl);
      this.copied = true;
    } catch {
      this.copied = false;
    }
  }

  private load(): Saved {
    try {
      const raw = JSON.parse(localStorage.getItem(this.key) || 'null');
      if (raw && Array.isArray(raw.ticks) && Number.isInteger(raw.opened)) {
        return { ticks: raw.ticks.filter((t: unknown) => typeof t === 'string'), opened: raw.opened };
      }
    } catch {
      /* storage unavailable or corrupt: start empty */
    }
    return { ticks: [], opened: 0 };
  }

  private save(): void {
    if (!this.shops) return;
    try {
      localStorage.setItem(this.key, JSON.stringify({ ticks: [...this.ticks], opened: this.opened }));
    } catch {
      /* private mode: ticks last for this visit only */
    }
  }
}
