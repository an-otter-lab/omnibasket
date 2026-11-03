import { Component, Input } from '@angular/core';
import { Candidate, LiveOffer, Outcome, outcomeOf, listingUrl, shopLabel, shopLink, sortOffers } from './live';
import { Lang, MESSAGES, Messages, fill } from './messages';

/** One row per shop the live read tried: its outcome, its price if one was read, its link. */
@Component({
  selector: 'app-shop-reads',
  template: `
    <section class="reads" aria-labelledby="reads-h">
      <h2 class="k" id="reads-h">{{ m.readsTitle }}</h2>
      @if (title) { <p class="pt">{{ title }}</p> }
      @if (noOfferAnywhere) {
        <div class="box no-offer-next" role="alert" data-state="no-offer">
          <p class="pt">{{ m.entryNoOffer }}</p>
          <div class="no-offer-actions">
            <a class="lnk" href="#/editions">{{ m.entryTryAnother }}</a>
          </div>
        </div>
      }
      <ul class="rlist">
        @for (o of rows; track o.store_id) {
          <li class="rrow" [attr.data-shop]="o.store_id" [attr.data-outcome]="kind(o)">
            <span class="col">
              <span class="strong">{{ name(o) }}</span>
              <span class="s" [class.warn]="warn(o)">{{ line(o) }}</span>
              @if (printingNote(o); as note) { <span class="s note" data-note="other-printing">{{ note }}</span> }
              @if (kind(o) === 'refused') { <span class="s">{{ m.readsRefusedLine }}</span> }
            </span>
            <span class="rowr">
              @if (o.price_cents != null) { <strong class="n">{{ lei(o.price_cents) }}</strong> }
              @if (link(o); as href) {
                <a class="store" [href]="href" target="_blank" rel="noopener" [attr.aria-label]="linkText(o)">{{ linkText(o) }}</a>
              }
            </span>
          </li>
        }
        @for (x of notChecked; track x.shop) {
          <li class="rrow" [attr.data-shop]="x.shop" data-outcome="not_checked">
            <span class="col">
              <span class="strong">{{ label(x.shop) }}</span>
              <span class="s">{{ m.readsNotChecked }}</span>
            </span>
            <span class="rowr">
              @if (listing(x.url); as href) {
                <a class="store" [href]="href" target="_blank" rel="noopener" [attr.aria-label]="openText(x.shop)">{{ openText(x.shop) }}</a>
              }
            </span>
          </li>
        }
      </ul>
    </section>
  `,
})
export class ShopReadsComponent {
  @Input() lang: Lang = 'en';
  @Input() offers: LiveOffer[] = [];
  @Input() pick: Candidate | null = null;
  @Input() isbn: string | null = null;
  @Input() title = '';

  get m() {
    return MESSAGES[this.lang];
  }

  get rows(): LiveOffer[] {
    const nc = new Set(this.notChecked.map((x) => this.key(x.shop)));
    return sortOffers(this.offers).filter((o) => !nc.has(this.key(o.store_id)));
  }

  /** Shops nobody read for this book: an honest line and a link, never "no offer". */
  get notChecked(): { shop: string; url: string }[] {
    // A shop that returned a price was read; one with only an empty row was not.
    const read = new Set(this.offers.filter((o) => o.price_cents != null || o.ranked).map((o) => this.key(o.store_id)));
    // Include shops from other_shops (from /search) and from offers (from /events?source=live)
    const fromOtherShops = (this.pick?.other_shops || []).filter((x) => x.status === 'not_checked' && !read.has(this.key(x.shop)));
    const fromOffers = this.offers
      .filter((o) => o.status === 'not_checked' && !read.has(this.key(o.store_id)))
      .map((o) => ({ shop: o.store_id, url: o.listing_url || '' }));
    // Merge and deduplicate
    const seen = new Set<string>();
    const result: { shop: string; url: string }[] = [];
    for (const x of [...fromOtherShops, ...fromOffers]) {
      const key = this.key(x.shop);
      if (!seen.has(key)) {
        seen.add(key);
        result.push(x);
      }
    }
    return result;
  }

  private key(id: string): string {
    return id.replace(/_/g, '-');
  }

  label(id: string): string {
    return shopLabel(id);
  }

  openText(id: string): string {
    return fill(this.m.readsOpen, { shop: shopLabel(id) });
  }

  get noOfferAnywhere(): boolean {
    return this.offers.length === 0 || this.offers.every((o) => outcomeOf(o) === 'no_offer');
  }

  name(o: LiveOffer): string {
    return shopLabel(o.store_id);
  }

  kind(o: LiveOffer): Outcome {
    return outcomeOf(o);
  }

  warn(o: LiveOffer): boolean {
    const k = outcomeOf(o);
    return k === 'refused' || k === 'no_price' || k === 'other_seller' || k === 'other';
  }

  link(o: LiveOffer): string | null {
    return shopLink(o, this.pick);
  }

  /** R11: a shop is linked only when we hold its listing page, never a search page. */
  listing(url: string | null | undefined): string | null {
    return listingUrl(url);
  }

  lei(cents: number): string {
    const lei = Math.floor(cents / 100);
    return lei.toLocaleString('ro-RO') + ',' + String(cents % 100).padStart(2, '0') + ' lei';
  }

  line(o: LiveOffer): string {
    const m = this.m;
    const shop = shopLabel(o.store_id);
    switch (outcomeOf(o)) {
      case 'ranked':
        return m.readsRanked;
      case 'not_compared':
        return m.readsNotCompared;
      case 'refused':
        return fill(m.readsRefused, { shop });
      case 'no_offer':
        return m.readsNoOffer;
      case 'no_price':
        return m.readsNoPrice;
      case 'not_live':
        return o.store_id === 'amazon_de' ? fill(m.readsNotLive, { shop }) : fill(m.readsNotLive, { shop });
      case 'other_seller':
        return fill(m.readsOtherSeller, { shop });
      default:
        return m.readsOther;
    }
  }

  /** Honest note when the shop's page carries another ISBN of the same work. */
  printingNote(o: LiveOffer): string | null {
    if (!o.other_printing || !o.isbn13) return null;
    return fill(this.m.readsOtherPrinting, { shop: shopLabel(o.store_id), isbn: o.isbn13 });
  }

  linkText(o: LiveOffer): string {
    return fill(this.m.readsOpen, { shop: shopLabel(o.store_id) });
  }

  t(key: keyof Messages, values: Record<string, string> = {}): string {
    return fill(this.m[key], values);
  }
}
