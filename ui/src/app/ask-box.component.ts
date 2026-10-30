import { Component, EventEmitter, Input, Output } from '@angular/core';
import { AskData, AskInputs, AskNext, AskTab, applyActions, askState, uiState } from './ask';
import { Lang, MESSAGES, Messages, fill } from './messages';

/** What the host applies: set the fields, solve, route, then call done(ok). ok=false: the pins were not possible and were rolled back. */
export interface AskApplied {
  next: AskNext;
  done: (ok: boolean) => void;
}

type ReplyKey = 'askDoneTab' | 'askDoneExclude' | 'askDoneInclude' | 'askDoneMembership' | 'askDoneMembershipOff' | 'askDonePinned' | 'askDonePinsCleared' | 'askUnsupported' | 'askUnavailable' | 'askBusy';
const REPLY_KEYS: readonly string[] = ['askDoneTab', 'askDoneExclude', 'askDoneInclude', 'askDoneMembership', 'askDoneMembershipOff', 'askDonePinned', 'askDonePinsCleared', 'askUnsupported', 'askUnavailable', 'askBusy'];

interface Reply { reply_key: string; reply_args?: Record<string, unknown> }
interface AskResponse extends Reply { status: 'ok' | 'unsupported'; actions: unknown[]; replies?: Reply[] }

@Component({
  selector: 'app-ask-box',
  template: `
    @if (data) {
      <section class="ask" [attr.aria-busy]="working || busy" aria-labelledby="ask-title">
        <h2 class="ask-title" id="ask-title">{{ m.askTitle }}</h2>
        <form class="ask-form" (submit)="$event.preventDefault(); send(value)">
          <input class="inp ask-inp" name="ask" type="text" maxlength="300" autocomplete="off" enterkeyhint="send"
            [attr.placeholder]="m.askPlaceholder" [attr.aria-label]="m.askTitle"
            [value]="value" [disabled]="working || busy" (input)="value = $any($event.target).value" />
          <button class="btn ask-go" type="submit" [disabled]="working || busy || !value.trim()">{{ m.askSubmit }}</button>
        </form>
        <div class="chips ask-chips">
          @for (ex of examples; track ex) {
            <button class="chip" type="button" [disabled]="working || busy" (click)="value = ex; send(ex)">{{ ex }}</button>
          }
        </div>
        <p class="s ask-reply" role="status" aria-live="polite">@for (line of lines; track $index) { <span>{{ line }}</span> }</p>
      </section>
    }
  `,
  styles: [`
    .ask { display: flex; flex-direction: column; gap: 8px; margin: 12px 0; }
    .ask-title { font: 600 14px Inter, sans-serif; color: var(--ink-2); margin: 0; }
    .ask-form { display: flex; gap: 8px; width: 100%; }
    .ask-inp { flex: 1 1 auto; min-width: 0; }
    .ask-go { flex: 0 0 auto; }
    .ask-inp:disabled { background: var(--disabled-bg); color: var(--ink-soft); }
    .ask-chips .chip:disabled { color: var(--ink-soft); cursor: not-allowed; }
    .ask-reply { margin: 0; display: flex; flex-direction: column; gap: 2px; color: var(--ink-2); }
    .ask-reply:empty { display: none; }
    @media (min-width: 834px) { .ask-form { max-width: 640px; } }
  `],
})
export class AskBoxComponent {
  @Input() lang: Lang = 'en';
  /** The current /solve payload; null (no data, or fixture mode) hides the box. */
  @Input() data: AskData | null = null;
  @Input() tab: AskTab = 'cheapest';
  @Input() selected: string[] | null = null;
  @Input() pins: Record<string, string> = {};
  @Input() memberships: string[] = [];
  /** The host is solving. */
  @Input() busy = false;
  @Output() applied = new EventEmitter<AskApplied>();

  value = '';
  working = false;
  lines: string[] = [];

  get m(): Messages { return MESSAGES[this.lang]; }
  get examples(): string[] { return [this.m.askExample1, this.m.askExample2, this.m.askExample3]; }

  private say(key: string, args: Record<string, unknown> = {}): string {
    const k = (REPLY_KEYS.includes(key) ? key : 'askUnsupported') as ReplyKey;
    const vals: Record<string, string> = {};
    for (const [a, v] of Object.entries(args)) vals[a] = String(a === 'tab' ? this.tabWord(String(v)) : v);
    return fill(this.m[k], vals);
  }
  private tabWord(t: string): string { return t === 'one' ? this.m.tabOne : t === 'custom' ? this.m.tabCustom : this.m.tabCheapest; }

  async send(text: string): Promise<void> {
    text = text.trim();
    if (!text || !this.data || this.working || this.busy) return;
    this.working = true;
    this.lines = [];
    try {
      const cur = { tab: this.tab, selected: this.selected, pins: this.pins, memberships: this.memberships };
      let res: Response;
      try {
        res = await fetch('/ask', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ text, lang: this.lang, state: askState(this.data, cur) }) });
      } catch {
        this.lines = [this.say('askUnavailable')];
        return;
      }
      if (res.status === 429) { this.lines = [this.say('askBusy')]; return; }
      if (res.status === 422) { this.lines = [this.say('askUnsupported')]; return; }
      if (!res.ok) { this.lines = [this.say('askUnavailable')]; return; }
      const body = (await res.json()) as AskResponse;
      if (body.status !== 'ok') { this.lines = [this.say(body.reply_key)]; return; }
      const next = applyActions(body.actions, uiState(this.data, cur));
      if (next.ignored || !Array.isArray(body.actions) || !body.actions.length) { this.lines = [this.say('askUnsupported')]; return; }
      const ok = await new Promise<boolean>((done) => this.applied.emit({ next, done }));
      const replies = body.replies?.length ? body.replies : [body];
      this.lines = replies.filter((r) => ok || r.reply_key !== 'askDonePinned').map((r) => this.say(r.reply_key, r.reply_args));
      if (!ok) this.lines.push(this.m.askPinsNotPossible);
      this.value = '';
    } finally {
      this.working = false;
    }
  }
}
