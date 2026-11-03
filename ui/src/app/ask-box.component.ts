import { Component, EventEmitter, Input, OnChanges, Output, SimpleChanges } from '@angular/core';
import { AskData, AskInputs, AskNext, AskPlan, AskTab, applyActions, askState, uiState } from './ask';
import { Lang, MESSAGES, Messages, fill } from './messages';
import { shopsThatTakeBooks } from './memberships';

/** What the host applies: set the fields, solve, route, then call done(ok, plan). ok=false: the pins were not possible and were rolled back.
 *  plan: what the solve gave, so the reply never claims a plan the page cannot show. */
export interface AskApplied {
  next: AskNext;
  done: (ok: boolean, plan?: AskPlan) => void;
}

type ReplyKey = 'askDoneTab' | 'askDoneExclude' | 'askDoneInclude' | 'askDoneMembership' | 'askDoneMembershipOff' | 'askDonePinned' | 'askDonePinsCleared' | 'askUnsupported' | 'askNotInBasket' | 'askOneNotPossible' | 'askUnavailable' | 'askBusy';
const REPLY_KEYS: readonly string[] = ['askDoneTab', 'askDoneExclude', 'askDoneInclude', 'askDoneMembership', 'askDoneMembershipOff', 'askDonePinned', 'askDonePinsCleared', 'askUnsupported', 'askNotInBasket', 'askOneNotPossible', 'askUnavailable', 'askBusy'];

interface Reply { reply_key: string; reply_args?: Record<string, unknown> }
interface AskResponse extends Reply { status: 'ok' | 'unsupported'; actions: unknown[]; replies?: Reply[] }
/** Replies that say where the plan landed; with no orders they give way to askNoPlan. */
const PLAN_REPLIES: readonly string[] = ['askDoneTab', 'askDoneExclude', 'askDoneInclude'];

@Component({
  selector: 'app-ask-box',
  template: `
    @if (data) {
      <section class="ask" [attr.aria-busy]="working || busy" aria-labelledby="ask-title">
        <h2 class="ask-title" id="ask-title">{{ m.askTitle }}</h2>
        <form class="ask-form" (submit)="$event.preventDefault(); send(value)">
          <label class="ask-label" for="ask-inp">{{ m.askLabel }}</label>
          <div class="ask-row">
            <input class="inp ask-inp" id="ask-inp" name="ask" type="text" maxlength="300" autocomplete="off" enterkeyhint="send"
              [attr.placeholder]="m.askPlaceholder" aria-describedby="ask-hint"
              [value]="value" [disabled]="working || busy" (input)="value = $any($event.target).value" />
            <button class="btn ask-go" type="submit" [disabled]="working || busy || !value.trim()">{{ m.askSubmit }}</button>
          </div>
          <p class="s ask-hint" id="ask-hint">{{ m.askHint }}</p>
        </form>
        <div class="chips ask-chips">
          @for (ex of examples; track $index) {
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
    .ask-form { display: flex; flex-direction: column; gap: 6px; width: 100%; }
    /* P3: the heading and the button already say "Ask"; the field keeps its label for screen readers only. */
    .ask-label { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0 0 0 0); clip-path: inset(50%); white-space: nowrap; border: 0; }
    /* R14: at 390 the field takes the whole row so the placeholder is never clipped; the button sits under it. */
    .ask-row { display: flex; flex-wrap: wrap; gap: 8px; width: 100%; min-width: 0; }
    .ask-inp { flex: 1 1 100%; min-width: 0; }
    .ask-go { flex: 0 0 auto; }
    .ask-inp:disabled { background: var(--disabled-bg); color: var(--ink-soft); }
    .ask-hint { margin: 0; color: var(--muted); font-size: 13px; line-height: 18px; }
    .ask-chips .chip:disabled { color: var(--ink-soft); cursor: not-allowed; }
    .ask-reply { margin: 0; display: flex; flex-direction: column; gap: 2px; color: var(--ink-2); }
    .ask-reply:empty { display: none; }
    @media (min-width: 480px) { .ask-inp { flex: 1 1 auto; } }
    @media (min-width: 834px) { .ask-row { max-width: 640px; } }
  `],
})
export class AskBoxComponent implements OnChanges {
  @Input() lang: Lang = 'en';
  /** The current /solve payload; null (no data, or fixture mode) hides the box. */
  @Input() data: AskData | null = null;
  @Input() tab: AskTab = 'cheapest';
  @Input() selected: string[] | null = null;
  @Input() pins: Record<string, string> = {};
  @Input() memberships: string[] = [];
  /** The custom selection is the pool Ask picks the cheapest from, after leaving shops out. */
  @Input() within = false;
  /** Shops Ask was told to leave out. */
  @Input() leftOut: string[] = [];
  /** The host is solving. */
  @Input() busy = false;
  @Output() applied = new EventEmitter<AskApplied>();

  value = '';
  working = false;
  lines: string[] = [];

  get m(): Messages { return MESSAGES[this.lang]; }
  /** R10: only what this basket can actually do — a membership chip needs a shop that can take a book. */
  /** S11: an example is offered only when it would change the answer on this tab. */
  get examples(): string[] {
    const orders = this.tabOrders;
    const out: string[] = [];
    if (orders.length > 1 && this.data?.one_order.answer) out.push(this.m.askExample1);
    if (orders.some((o) => o.store_id === 'amazon_de')) out.push(this.m.askExample2);
    for (const r of this.membershipExamples) out.push(fill(this.m.membershipDeclare, { name: r.name }));
    return out;
  }
  private get membershipExamples(): { id: string; name: string }[] {
    const d = this.data;
    if (!d) return [];
    const can = shopsThatTakeBooks(d.shops || [], this.tabOrders);
    return (d.memberships || [])
      .filter((r) => !!r.store_id && can.has(r.store_id))
      .map((r) => ({ id: r.id, name: r.name || r.id }));
  }
  private get tabOrders(): { store_id?: string }[] {
    const d = this.data;
    if (!d) return [];
    if (this.tab === 'one') return d.one_order.answer?.orders || [];
    if (this.tab === 'custom') return d.custom?.orders || [];
    return d.cheapest.orders || [];
  }

  // R14: an answer written in the old language is cleared on a switch; the field keeps its focus.
  ngOnChanges(changes: SimpleChanges): void {
    if (changes['lang'] && !changes['lang'].firstChange) this.lines = [];
  }

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
      const cur = { tab: this.tab, selected: this.selected, pins: this.pins, memberships: this.memberships, within: this.within, leftOut: this.leftOut };
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
      if (body.status !== 'ok') { this.lines = (body.replies?.length ? body.replies : [body]).map((r) => this.say(r.reply_key, r.reply_args)); return; }
      const next = applyActions(body.actions, uiState(this.data, cur));
      if (next.ignored || !Array.isArray(body.actions) || !body.actions.length) { this.lines = [this.say('askUnsupported')]; return; }
      const { ok, plan } = await new Promise<{ ok: boolean; plan?: AskPlan }>((resolve) =>
        this.applied.emit({ next, done: (ok, plan) => resolve({ ok, plan }) }));
      this.value = '';
      const replies = (body.replies?.length ? body.replies : [body]).filter((r) => ok || r.reply_key !== 'askDonePinned');
      if (plan && !plan.orders) {
        // The page has no total: a tab or shop reply becomes askNoPlan, never "Showing …" or "Left out …".
        // A membership or edition reply stays: that change was applied.
        const kept = replies.filter((r) => !PLAN_REPLIES.includes(r.reply_key));
        this.lines = [...(kept.length < replies.length ? [this.m.askNoPlan] : []), ...kept.map((r) => this.say(r.reply_key, r.reply_args))];
      } else {
        // "Showing 1 order" only when the page shows one order holding every book, whichever tab it landed on.
        const one = !plan ? '' : plan.orders > 1 ? fill(this.m.askOneTakesMore, { n: String(plan.orders) })
          : plan.missing.length ? fill(this.m.askOneLeavesOut, { books: plan.missing.join(', ') }) : '';
        this.lines = replies.map((r) => one && r.reply_key === 'askDoneTab' && r.reply_args?.['tab'] === 'one' ? one : this.say(r.reply_key, r.reply_args));
      }
      if (!ok) this.lines.push(this.m.askPinsNotPossible);
    } finally {
      this.working = false;
    }
  }
}
