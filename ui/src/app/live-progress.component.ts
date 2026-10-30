import { Component, EventEmitter, Input, Output } from '@angular/core';
import { Progress, shopLabel } from './live';
import { Lang, MESSAGES, fill } from './messages';

/** Progress lines in the order they arrive from /events. */
@Component({
  selector: 'app-live-progress',
  template: `
    <h1 class="h2">{{ heading }}</h1>
    @if (!failed) { <p class="s" role="status">{{ m.progWait }}</p> }
    <ol class="plog" aria-live="polite" aria-label="Read progress">
      @for (p of lines; track $index) {
        <li [attr.data-status]="p.status" [attr.data-shop]="p.store_id">
          <span class="dot" [class.run]="p.status === 'reading'" aria-hidden="true">{{ mark(p.status) }}</span>
          <span class="pmsg">{{ p.message }}</span>
          <span class="s">{{ word(p.status) }}</span>
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

  mark(status: string): string {
    return status === 'ok' || status === 'cache' ? '✓' : status === 'failed' ? '✕' : status === 'skipped' ? '–' : '';
  }

  word(status: string): string {
    const m = this.m;
    return status === 'reading' ? m.progLineReading : status === 'ok' || status === 'cache' ? m.progLineOk : status === 'failed' ? m.progLineFailed : m.progLineSkipped;
  }

  shop(id: string): string {
    return shopLabel(id);
  }
}
