import { Component, EventEmitter, Input, Output, ViewChild, ElementRef } from '@angular/core';
import { Lang, MESSAGES } from './messages';
import { MAX_PHOTO_BYTES, PhotoReadResponse } from './photo';

export type PhotoInputEvent =
  | { kind: 'oversize'; size: number }
  | { kind: 'read'; response: PhotoReadResponse }
  | { kind: 'error' };

/** The photo control beside the one box. Accepts image/* from file picker or camera. */
@Component({
  selector: 'app-photo-input',
  template: `
    <input
      #fileInput
      class="photo-inp"
      type="file"
      accept="image/*"
      capture="environment"
      [attr.aria-label]="m.photoAriaLabel"
      (change)="onFile($event)"
    />
    <button class="btn photo-btn" type="button" [disabled]="busy" (click)="fileInput.click()">
      {{ m.photoButton }}
    </button>
  `,
  styles: [
    `
      .photo-inp {
        position: absolute;
        width: 1px;
        height: 1px;
        overflow: hidden;
        clip: rect(0 0 0 0);
        white-space: nowrap;
      }
      .photo-btn {
        min-width: 5rem;
      }
    `,
  ],
})
export class PhotoInputComponent {
  @ViewChild('fileInput') fileInput!: ElementRef<HTMLInputElement>;
  @Input() lang: Lang = 'en';
  @Input() busy = false;
  @Output() photoEvent = new EventEmitter<PhotoInputEvent>();

  get m() {
    return MESSAGES[this.lang];
  }

  async onFile(event: Event): Promise<void> {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0];
    if (!file) return;
    // Reset the input so the same file can be re-selected.
    input.value = '';

    if (file.size > MAX_PHOTO_BYTES) {
      this.photoEvent.emit({ kind: 'oversize', size: file.size });
      return;
    }

    try {
      const buffer = await file.arrayBuffer();
      const res = await fetch('/photo', {
        method: 'POST',
        headers: { 'content-type': file.type || 'application/octet-stream' },
        body: buffer,
      });
      const json = (await res.json()) as PhotoReadResponse;
      this.photoEvent.emit({ kind: 'read', response: json });
    } catch {
      this.photoEvent.emit({ kind: 'error' });
    }
  }
}
