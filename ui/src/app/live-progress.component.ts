import { Component, EventEmitter, Input, Output } from '@angular/core';
import { Progress, shopLabel } from './live';
import { Lang, MESSAGES, fill } from './messages';

/** Progress lines in the order they arrive from /events. */
@Component({
  selector: 'app-live-progress',
  template: `
    <h1 class="h2">{{ heading }}</h1>
    @if (!failed) { <p class="s" role="status">{{ m.progWait }}</p> }
    <ol class="plog" aria-live="polite" [attr.aria-label]="m.progLabel">
      @for (p of lines; track $index) {
        <li [attr.data-status]="p.status" [attr.data-shop]="p.store_id">
          <span class="dot" [class.run]="p.status === 'reading'" aria-hidden="true">{{ mark(p) }}</span>
          <span class="pmsg">{{ line(p) }}</span>
          <span class="s">{{ word(p) }}</span>
        </li>
      }
    </ol>
    @if (failed) {
      <div class="box" role="alert" data-state="read-failed">
        <p class="pt">{{ m.progFailed }}</p>
        <div class="btnrow"><button class="btn" type="button" (click)="retry.emit()">{{ m.progRetry }}</button></div>
      </div>
    }
  `,
})
export class LiveProgressComponent {
  @Input() lang: Lang = 'en';
  @Input() title = '';
  @Input() lines: Progress[] = [];
  @Input() failed = false;
  @Output() retry = new EventEmitter<void>();

  get m() {
    return MESSAGES[this.lang];
  }

  get heading(): string {
    return fill(this.m.progTitle, { title: this.title });
  }

  /** S9: Amazon.de is never read live, whatever status the stream carries. */
  notLive(p: Progress): boolean {
    return p.store_id === 'amazon_de' && p.status !== 'reading';
  }

  /** S9: the line comes from the shop and its status in the shopper's language, never the server's text. */
  line(p: Progress): string {
    const m = this.m;
    const key =
      p.status === 'reading' ? m.progShopReading
      : this.notLive(p) ? m.progShopNotLive
      : p.status === 'ok' ? m.progShopRead
      : p.status === 'cache' ? m.progShopCache
      : p.status === 'failed' ? m.progShopFailed
      : p.status === 'skipped' ? m.progShopNotIndexed
      : m.progShopNotChecked;
    return fill(key, { shop: shopLabel(p.store_id) });
  }

  mark(p: Progress): string {
    const status = this.notLive(p) ? 'skipped' : p.status;
    return status === 'ok' || status === 'cache' ? '✓' : status === 'failed' ? '✕' : status === 'skipped' || status === 'not_checked' ? '–' : '';
  }

  word(p: Progress): string {
    const status = this.notLive(p) ? 'skipped' : p.status;
    const m = this.m;
    return status === 'reading' ? m.progLineReading : status === 'ok' || status === 'cache' ? m.progLineOk : status === 'failed' ? m.progLineFailed : m.progLineSkipped;
  }

  shop(id: string): string {
    return shopLabel(id);
  }
}
