import { Component, EventEmitter, Input, Output } from '@angular/core';
import { Lang, MESSAGES, Messages, fill } from './messages';
import { MembershipRow, membershipNote, membershipSource, saveDeclared } from './memberships';

// Feature 5: "I have Prime" / "I have Genius" toggles in the result controls.
// Standalone; the parent re-solves with the declared ids it emits.
@Component({
  selector: 'app-memberships',
  standalone: true,
  styles: [
    '.mships{margin:10px 0 0}',
    '.mships label{display:inline-flex;align-items:center;gap:6px;margin-right:14px;cursor:pointer}',
    '.mships input{width:18px;height:18px;accent-color:#14532d}',
    '.mnote{margin:6px 0 0}',
    '.msrc{word-break:break-all}',
  ],
  template: `
    @if (rows.length) {
      <fieldset class="mships box">
        <legend class="s n">{{ m.membershipsTitle }}</legend>
        <p class="s">{{ m.membershipsIntro }}</p>
        @for (r of rows; track r.id) {
          <label [attr.data-membership]="r.id">
            <input type="checkbox" [checked]="isOn(r.id)" (change)="toggle(r.id)" />
            <span>{{ declareText(r) }}</span>
          </label>
        }
        @for (r of rows; track r.id) {
          @if (isOn(r.id)) {
            <div class="mnote" [attr.data-membership-note]="r.id" role="status">
              <p class="s ink">{{ note(r) }}</p>
              <p class="s msrc"><a class="lnk" [href]="r.source_url" target="_blank" rel="noopener noreferrer">{{ source(r) }}</a></p>
            </div>
          }
        }
      </fieldset>
    }
  `,
})
export class MembershipsComponent {
  @Input() rows: MembershipRow[] = [];
  @Input() declared: string[] = [];
  @Input() lang: Lang = 'en';
  @Output() declaredChange = new EventEmitter<string[]>();

  get m(): Messages {
    return MESSAGES[this.lang];
  }

  isOn(id: string): boolean {
    return this.declared.includes(id);
  }

  declareText(r: MembershipRow): string {
    return fill(this.m.membershipDeclare, { name: r.name });
  }

  note(r: MembershipRow): string {
    const text = membershipNote(r, this.lang);
    return r.changes_totals ? text : text + ' ' + this.m.membershipTotalsSame;
  }

  source(r: MembershipRow): string {
    return membershipSource(r, this.lang);
  }

  toggle(id: string): void {
    const next = this.isOn(id) ? this.declared.filter((d) => d !== id) : [...this.declared, id];
    this.declared = next;
    saveDeclared(next);
    this.declaredChange.emit(next);
  }
}
