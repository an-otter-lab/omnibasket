import { Component, EventEmitter, Input, Output } from '@angular/core';
import { Candidate, coverUrl, initials, shopLabel } from './live';
import { Lang, MESSAGES, fill } from './messages';

export type PickState = 'searching' | 'results' | 'empty' | 'error' | 'link_failed';

/** A short list of candidate books. Covers come from Open Library only. */
@Component({
  selector: 'app-pick-list',
  template: `
    @switch (state) {
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
        <p class="p" role="status" data-state="empty">{{ m.pickEmpty }}</p>
      }
      @default {
        <h2 class="h2">{{ m.pickTitle }}</h2>
        <ul class="picks">
          @for (c of items; track $index) {
            <li>
              <button class="pick" type="button" [disabled]="!c.isbn" (click)="picked.emit(c)">
                @if (cover(c); as src) {
                  <img class="pcover" [src]="src" [attr.data-initials]="initialsOf(c)" alt="" width="56" height="80" loading="lazy" referrerpolicy="no-referrer" (error)="broken($event)" />
                } @else {
                  <span class="pcover ph" aria-hidden="true">{{ initialsOf(c) }}</span>
                }
                <span class="pmeta">
                  <span class="pt">{{ c.title }}</span>
                  @if (c.author) { <span class="s">{{ c.author }}</span> }
                  @if (!c.isbn) { <span class="s unk">{{ m.pickNoIsbn }}</span> }
                  @if (c.shops.length) { <span class="s">{{ listed(c) }}</span> }
                </span>
                @if (c.isbn) { <span class="pgo">{{ m.pickRead }} ›</span> }
              </button>
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

  get m() {
    return MESSAGES[this.lang];
  }

  initialsOf(c: Candidate): string {
    return initials(c.title);
  }

  cover(c: Candidate): string | null {
    return coverUrl(c);
  }

  listed(c: Candidate): string {
    const names = [...new Set(c.shops.map((s) => shopLabel(s.shop)))];
    return fill(this.m.pickListed, { shops: names.join(', ') });
  }

  /** A cover Open Library does not have: swap in the plain placeholder, never another image. */
  broken(ev: Event): void {
    const img = ev.target as HTMLImageElement;
    const ph = document.createElement('span');
    ph.className = 'pcover ph';
    ph.setAttribute('aria-hidden', 'true');
    ph.textContent = img.dataset['initials'] || '·';
    img.replaceWith(ph);
  }
}
