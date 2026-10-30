import { Component, EventEmitter, Input, Output } from '@angular/core';
import { Lang, MESSAGES, fill } from './messages';
import { PhotoCandidate, PhotoLineAmbiguous, PhotoLineNotFound, PhotoState, ResolvedLine, coverOf, editionLabel } from './photo';

/** The photo result screen: matched, ambiguous (with pick lists), not found. */
@Component({
  selector: 'app-photo-result',
  template: `
    @switch (state.kind) {
      @case ('reading') {
        <p class="p" role="status">{{ m.photoReading }}</p>
      }
      @case ('oversize') {
        <div class="box" role="alert">
          <p class="pt">{{ oversizeMessage }}</p>
        </div>
      }
      @case ('failed') {
        <div class="box" role="alert">
          <p class="pt">{{ m.photoReadFail }}</p>
        </div>
      }
      @case ('result') {
        @if (state.matched.length) {
          <section class="photo-section">
            <h2 class="h3">{{ matchedCountMessage }}</h2>
            @for (line of state.matched; track line.candidate.isbn) {
              <div class="photo-card">
                @if (coverOf(line.candidate); as src) {
                  <img class="pcover" [src]="src" alt="" width="56" height="80" loading="lazy" referrerpolicy="no-referrer" />
                } @else {
                  <span class="pcover ph" aria-hidden="true"></span>
                }
                <div class="pmeta">
                  <p class="pt">{{ line.candidate.title }}</p>
                  @if (line.candidate.author) { <p class="s">{{ line.candidate.author }}</p> }
                  @if (line.candidate.edition) { <p class="s n">{{ editionLabel(line.candidate.edition) }}</p> }
                  <p class="s n">ISBN {{ line.candidate.isbn }}</p>
                </div>
              </div>
            }
          </section>
        }
        @if (state.ambiguous.length) {
          <section class="photo-section">
            <h2 class="h3">{{ ambiguousCountMessage }}</h2>
            @for (item of state.ambiguous; track $index) {
              <div class="photo-ambiguous">
                <p class="pt">{{ item.line.read_title }}</p>
                @if (item.line.read_author) { <p class="s">{{ item.line.read_author }}</p> }
                <p class="pick-title">{{ pickEditionMessage(item.line) }}</p>
                <ul class="picks">
                  @for (c of item.line.candidates; track c.isbn) {
                    <li>
                      <button class="pick" type="button" [class.sel]="item.picked?.isbn === c.isbn" (click)="pick.emit({ index: $index, candidate: c })">
                        @if (coverOf(c); as src) {
                          <img class="pcover" [src]="src" alt="" width="56" height="80" loading="lazy" referrerpolicy="no-referrer" />
                        } @else {
                          <span class="pcover ph" aria-hidden="true"></span>
                        }
                        <span class="pmeta">
                          <span class="pt">{{ c.title }}</span>
                          @if (c.author) { <span class="s">{{ c.author }}</span> }
                          @if (c.edition) { <span class="s n">{{ editionLabel(c.edition) }}</span> }
                          <span class="s n">ISBN {{ c.isbn }}</span>
                        </span>
                        <span class="pgo">{{ m.photoPick }} ›</span>
                      </button>
                    </li>
                  }
                </ul>
              </div>
            }
          </section>
        }
        @if (state.notFound.length) {
          <section class="photo-section">
            <h2 class="h3">{{ notFoundCountMessage }}</h2>
            <p class="s ink">{{ m.photoNotFoundTitle }}</p>
            <ul class="notfound">
              @for (line of state.notFound; track $index) {
                <li>
                  <p class="pt">{{ line.read_title }}</p>
                  @if (line.read_author) { <p class="s">{{ line.read_author }}</p> }
                </li>
              }
            </ul>
          </section>
        }
        @if (canContinue) {
          <button class="btn full" type="button" (click)="continue.emit()">{{ m.photoContinue }}</button>
        }
      }
    }
  `,
  styles: [
    `
      .photo-section {
        margin-bottom: 1.5rem;
      }
      .photo-card,
      .photo-ambiguous {
        display: flex;
        gap: 0.75rem;
        margin-bottom: 1rem;
      }
      .photo-card .pmeta,
      .photo-ambiguous .pmeta {
        flex: 1;
      }
      .pick-title {
        font-size: 0.875rem;
        color: #6b6b6b;
        margin: 0.5rem 0;
      }
      .picks {
        list-style: none;
        padding: 0;
        margin: 0;
      }
      .picks li {
        margin-bottom: 0.5rem;
      }
      .pick {
        display: flex;
        align-items: center;
        gap: 0.75rem;
        width: 100%;
        padding: 0.5rem;
        border: 1px solid #ddd;
        border-radius: 4px;
        background: #fff;
        cursor: pointer;
        text-align: left;
      }
      .pick.sel {
        border-color: #0066cc;
        background: #f0f7ff;
      }
      .pick .pmeta {
        flex: 1;
      }
      .pick .pgo {
        color: #0066cc;
        font-weight: 500;
      }
      .notfound {
        list-style: none;
        padding: 0;
        margin: 0;
      }
      .notfound li {
        padding: 0.5rem 0;
        border-bottom: 1px solid #eee;
      }
      .notfound li:last-child {
        border-bottom: none;
      }
    `,
  ],
})
export class PhotoResultComponent {
  @Input() lang: Lang = 'en';
  @Input() state: PhotoState = { kind: 'idle' };
  @Output() pick = new EventEmitter<{ index: number; candidate: PhotoCandidate }>();
  @Output() continue = new EventEmitter<void>();

  get m() {
    return MESSAGES[this.lang];
  }

  get oversizeMessage(): string {
    if (this.state.kind !== 'oversize') return '';
    const mb = (this.state.size / (1024 * 1024)).toFixed(1);
    return fill(this.m.photoOversize, { size: mb + ' MB' });
  }

  get matchedCountMessage(): string {
    if (this.state.kind !== 'result') return '';
    return fill(this.m.photoMatchedCount, { n: String(this.state.matched.length) });
  }

  get ambiguousCountMessage(): string {
    if (this.state.kind !== 'result') return '';
    return fill(this.m.photoAmbiguousCount, { n: String(this.state.ambiguous.length) });
  }

  get notFoundCountMessage(): string {
    if (this.state.kind !== 'result') return '';
    return fill(this.m.photoNotFoundCount, { n: String(this.state.notFound.length) });
  }

  pickEditionMessage(line: PhotoLineAmbiguous): string {
    return fill(this.m.photoPickEdition, { title: line.read_title });
  }

  editionLabel(e: string | undefined): string {
    return editionLabel(e);
  }

  coverOf(c: PhotoCandidate): string | null {
    return coverOf(c);
  }

  get canContinue(): boolean {
    if (this.state.kind !== 'result') return false;
    // Can continue if we have matched lines or all ambiguous are picked.
    if (this.state.matched.length > 0) return true;
    return this.state.ambiguous.every((a) => a.picked !== null);
  }
}
