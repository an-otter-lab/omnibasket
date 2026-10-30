import { Component, EventEmitter, Input, Output } from '@angular/core';
import { Lang, MESSAGES } from './messages';

/** The first screen's one input. The sample basket is a quiet link under it. */
@Component({
  selector: 'app-input-box',
  template: `
    <form class="onebox" (submit)="$event.preventDefault(); send()">
      <input
        class="inp big-inp"
        name="q"
        type="search"
        enterkeyhint="search"
        autocomplete="off"
        autocapitalize="off"
        spellcheck="false"
        [attr.placeholder]="m.boxPlaceholder"
        [attr.aria-label]="m.boxPlaceholder"
        [value]="value"
        (input)="value = $any($event.target).value"
      />
      <button class="btn" type="submit">{{ m.boxFind }}</button>
    </form>
    @if (showSample) {
      <p class="sample"><a class="lnk" href="?sample=ro-v1#/result/cheapest" data-sample>{{ m.boxSample }}</a></p>
    }
  `,
})
export class InputBoxComponent {
  @Input() lang: Lang = 'en';
  @Input() value = '';
  @Input() showSample = false;
  @Output() submitted = new EventEmitter<string>();

  get m() {
    return MESSAGES[this.lang];
  }

  send(): void {
    const text = this.value.trim();
    if (text) this.submitted.emit(text);
  }
}
