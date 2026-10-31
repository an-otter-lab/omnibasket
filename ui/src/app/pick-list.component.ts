import { Component, EventEmitter, Input, Output } from '@angular/core';
import { Candidate, coverFallback, coverUrl, initials, listingUrl, shopLabel } from './live';
import { Lang, MESSAGES, Messages, fill } from './messages';

export type PickState = 'idle' | 'searching' | 'results' | 'empty' | 'error' | 'link_failed';

/** A short list of candidate books. Covers come from Open Library only. */
@Component({
  selector: 'app-pick-list',
  template: `
    @switch (state) {
      @case ('idle') {
        <!-- Nothing to list: the field is empty and this screen has no search running. -->
      }
      @case ('searching') {
        <p class="p" role="status">{{ m.pickSearching }}</p>
      }
      @case ('error') {
        <p class="p" role="alert" data-state="search-error">{{ m.pickSearchError }}</p>
      }
      @case ('link_failed') {
        <div class="box" role="alert" data-state="link-failed">
          <p class="pt">{{ m.pickLinkFail }}</p>
          <p class="s">{{ m.pickLinkFailHint }}</p>
        </div>
      }
      @case ('empty') {
        <div class="box" role="status" data-state="empty">
          <p class="p">{{ m.pickEmpty }}</p>
          <button class="lnk" type="button" data-action="clear" (click)="cleared.emit()">{{ m.pickClear }}</button>
        </div>
      }
      @default {
        <h2 class="h2">{{ m.pickTitle }}</h2>
        <ul class="picks">
          @for (c of items; track $index) {
            <li class="pickcard">
              <!-- R15: the whole row is one native button: Enter and Space activate it, the keyboard reaches it. -->
              <button class="pick" type="button" data-action="pick" [disabled]="!c.isbn" (click)="picked.emit(c)">
                @if (cover(c); as src) {
                  <img class="pcover" [src]="src" [attr.data-initials]="initialsOf(c)" alt="" width="56" height="80" loading="lazy" referrerpolicy="no-referrer" (error)="broken($event)" (load)="broken($event)" />
                } @else {
                  <span class="pcover ph" aria-hidden="true">{{ initialsOf(c) }}</span>
                }
                <span class="pmeta">
                  <span class="pt">{{ c.title }}</span>
                  @if (c.author) { <span class="s">{{ c.author }}</span> }
                  @if (!c.isbn) { <span class="s unk">{{ m.pickNoIsbn }}</span> }
                  @if (c.shops.length) { <span class="s">{{ listed(c) }}</span> }
                </span>
                @if (c.isbn) { <span class="pgo">{{ m.pickRead }}<span class="pchev" aria-hidden="true"> ›</span></span> }
              </button>
              @if (unchecked(c).length) {
                <p class="not-checked" data-not-checked>
                  <span class="nclabel">{{ m.notCheckedLabel }}</span>
                  @for (x of unchecked(c); track x.shop; let last = $last) {
                    @if (listing(x); as href) {
                      <a class="nclink" [href]="href" target="_blank" rel="noopener" [attr.aria-label]="t('pickOpenListing', { shop: label(x.shop) })">{{ label(x.shop) }} ↗</a>
                    } @else {
                      <span class="ncshop">{{ label(x.shop) }}</span>
                    }
                    @if (!last) {<span class="ncsep" aria-hidden="true">,</span>}
                  }
                </p>
              }
            </li>
          }
        </ul>
      }
    }
  `,
})
export class PickListComponent {
  @Input() lang: Lang = 'en';
  @Input() state: PickState = 'results';
  @Input() items: Candidate[] = [];
  @Output() picked = new EventEmitter<Candidate>();
  /** R0: the no-match message's Clear button, handled by the add-book state. */
  @Output() cleared = new EventEmitter<void>();

  get m() {
    return MESSAGES[this.lang];
  }

  initialsOf(c: Candidate): string {
    return initials(c.title);
  }

  cover(c: Candidate): string | null {
    return coverUrl(c);
  }

  unchecked(c: Candidate) {
    return (c.other_shops || []).filter((x) => x.status === 'not_checked');
  }

  /** R11: only a listing page is linked; a shop search URL never is. */
  listing(x: { url?: string | null }): string | null {
    return listingUrl(x.url);
  }

  label(id: string): string {
    return shopLabel(id);
  }

  t(key: keyof Messages, values: Record<string, string> = {}): string {
    return fill(this.m[key], values);
  }

  listed(c: Candidate): string {
    const names = [...new Set(c.shops.map((s) => shopLabel(s.shop)))];
    return fill(this.m.pickListed, { shops: names.join(', ') });
  }

  /** A cover Open Library does not have: swap in the plain placeholder, never another image (S27: shared). */
  broken(ev: Event): void {
    coverFallback(ev);
  }
}
