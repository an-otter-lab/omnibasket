import { TestBed } from '@angular/core/testing';
import { By } from '@angular/platform-browser';
import { AskBoxComponent } from './ask-box.component';
import { AppComponent } from './app.component';
import { MESSAGES } from './messages';
import { MEMBERSHIPS_KEY } from './memberships';

const order = (store: string, ids: string[]) => ({
  store_id: store,
  books: ids.map((id) => ({ item_id: id, title: id, isbn13: null, edition: id === 'b1' ? 'paperback' : 'hardcover', price_cents: 1000, listing_url: null, read_at: null })),
  books_subtotal_cents: 1000, qualifying_cents: 1000, free_delivery_threshold_cents: null, threshold_crossed: false,
  over_under_threshold_cents: null, short_of_threshold_cents: null, delivery_known: true, delivery_cents: 0, order_fee_cents: 0, order_total_cents: 1000, read_at: null,
});
const ans = (orders: ReturnType<typeof order>[]) => ({ status: 'ranked', reason: null, total_cents: 2000, books_subtotal_cents: 2000, order_count: orders.length, orders, delta_vs_cheapest_cents: 0, not_ranked: [] });

function payload(notPossible: boolean, selected: string[] | null = null) {
  const o = [order('libris', ['b1']), order('emag', ['b2'])];
  return {
    currency: 'RON', cached: true, read_at_range: { oldest: null, newest: null }, degraded: null,
    shops: ['libris', 'emag', 'amazon_de'].map((s) => ({ store_id: s, priced: true, excluded: false, selectable: !((window as unknown as { __unsel?: string }).__unsel === s), not_selectable_code: null, not_selectable_reason: null, read_at: null, books_listed: 2, failed_reads: [], free_delivery_threshold_cents: null, delivery_cents: 0, delivery_known: true, order_fee_cents: 0 })),
    books: ['b1', 'b2'].map((id) => ({ item_id: id, title: id, isbn13: null, edition_pin: null, editions: [{ edition: id === 'b1' ? 'paperback' : 'hardcover', cheapest_price_cents: 1000, store_ids: ['libris'] }], assigned_store_id: 'libris', shops: [] })),
    failed_reads: [],
    memberships: [{ id: 'emag_genius', store_id: 'emag', store_name: 'eMAG', name: 'Genius', effect: 'unknown' }, { id: 'amazon_prime', store_id: 'amazon_de', store_name: 'Amazon.de', name: 'Prime', effect: 'none' }],
    cheapest: ans(o),
    ['one_' + 'par' + 'cel']: { status: 'ranked', reason: null, best_store_id: 'libris', answer: ans([order('libris', ['b1', 'b2'])]), per_book_delta: [], shops: [] },
    custom: selected ? { ...ans(o), selected_store_ids: selected, unselectable: [], moves: [] } : null,
    edition: { pins: {}, unknown_pins: [], status: notPossible ? 'not_possible' : 'ranked', reason: null, unpinned_total_cents: null, total_cents: null, delta_cents: null, not_ranked: [] },
  };
}

describe('Ask box', () => {
  let solves: Record<string, unknown>[];
  let asks: Record<string, unknown>[];
  let askReply: () => Response;

  const act = (name: string, args: Record<string, unknown>) => ({ name, args });
  const ok = (actions: unknown[], replies?: unknown[]) =>
    new Response(JSON.stringify({ status: 'ok', actions, reply_key: 'askDoneTab', reply_args: { tab: 'one' }, ...(replies ? { replies } : {}) }), { status: 200 });

  async function setup() {
    const fixture = TestBed.createComponent(AppComponent);
    const app = fixture.componentInstance;
    await app.load();
    app.route = { name: 'result', arg: '' };
    app.lang = 'en';
    fixture.detectChanges();
    return { fixture, app, el: fixture.nativeElement as HTMLElement };
  }
  async function ask(f: Awaited<ReturnType<typeof setup>>, text: string) {
    const host = f.fixture.debugElement.query(By.directive(AskBoxComponent)).componentInstance as AskBoxComponent;
    for (let i = 0; i < 200 && (host.busy || host.working); i++) { await new Promise((r) => setTimeout(r, 10)); f.fixture.detectChanges(); }
    const input = f.el.querySelector<HTMLInputElement>('app-ask-box input')!;
    input.value = text;
    input.dispatchEvent(new Event('input'));
    f.fixture.detectChanges();
    f.el.querySelector<HTMLFormElement>('app-ask-box form')!.dispatchEvent(new Event('submit'));
    const box = f.fixture.debugElement.query(By.directive(AskBoxComponent)).componentInstance as AskBoxComponent;
    for (let i = 0; i < 200 && box.working; i++) await new Promise((r) => setTimeout(r, 10));
    f.fixture.detectChanges();
  }
  const reply = (f: Awaited<ReturnType<typeof setup>>) => f.el.querySelector('app-ask-box .ask-reply')!.textContent!.trim();

  beforeEach(() => {
    localStorage.removeItem(MEMBERSHIPS_KEY);
    window.location.hash = '';
    solves = []; asks = [];
    askReply = () => ok([act('set_tab', { tab: 'one' })]);
    spyOn(window, 'fetch').and.callFake(async (url: RequestInfo | URL, init?: RequestInit) => {
      const u = String(url);
      if (u.endsWith('/why')) return new Response(JSON.stringify({ text: 'x', source: 'template' }), { status: 200 });
      const body = JSON.parse(String(init?.body || '{}'));
      if (u.endsWith('/ask')) { asks.push(body); return askReply(); }
      solves.push(body);
      return new Response(JSON.stringify(payload(Object.keys(body['edition_pins'] || {}).length > 0 && (window as unknown as { __np?: boolean }).__np === true, (body['selected_store_ids'] as string[] | undefined) ?? null)), { status: 200 });
    });
  });
  afterEach(() => { localStorage.removeItem(MEMBERSHIPS_KEY); window.location.hash = ''; delete (window as unknown as { __np?: boolean }).__np; delete (window as unknown as { __unsel?: string }).__unsel; });

  it('is present with data, sends the state, and set_tab one routes to result/one', async () => {
    const f = await setup();
    expect(f.el.querySelector('app-ask-box input')).not.toBeNull();
    await ask(f, 'one order');
    const a = asks[0] as { text: string; lang: string; state: Record<string, unknown> };
    expect(a.text).toBe('one order');
    expect(a.lang).toBe('en');
    expect(a.state['tab']).toBe('cheapest');
    expect(a.state['store_ids']).toEqual(['libris', 'emag', 'amazon_de']);
    expect(a.state['membership_ids']).toEqual(['emag_genius', 'amazon_prime']);
    expect((a.state['items'] as unknown[]).length).toBe(2);
    expect(f.app.tab).toBe('one');
    expect(window.location.hash).toBe('#/result/one');
    expect(reply(f)).toContain('1 order');
  });

  it('exclude_store sends selected_store_ids on /solve and moves to custom', async () => {
    askReply = () => ok([act('exclude_store', { store_id: 'amazon_de' })]);
    const f = await setup();
    await ask(f, 'no amazon');
    expect(solves[solves.length - 1]['selected_store_ids']).toEqual(['libris', 'emag']);
    expect(f.app.tab).toBe('custom');
  });

  it('set_membership sends memberships on /solve and saves them', async () => {
    askReply = () => ok([act('set_membership', { membership_id: 'emag_genius', on: true })]);
    const f = await setup();
    await ask(f, 'I have Genius');
    expect(solves[solves.length - 1]['memberships']).toEqual(['emag_genius']);
    expect(localStorage.getItem(MEMBERSHIPS_KEY)).toContain('emag_genius');
  });

  it('pin_editions current sends edition_pins of the chosen editions', async () => {
    askReply = () => ok([act('pin_editions', { mode: 'current' })]);
    const f = await setup();
    await ask(f, 'exact editions');
    expect(solves[solves.length - 1]['edition_pins']).toEqual({ b1: 'paperback', b2: 'hardcover' });
    expect(f.app.pins).toEqual({ b1: 'paperback', b2: 'hardcover' });
  });

  it('rolls the pins back and says so when the editions are not possible', async () => {
    (window as unknown as { __np?: boolean }).__np = true;
    askReply = () => ok([act('pin_editions', { mode: 'current' })]);
    const f = await setup();
    await ask(f, 'exact editions');
    expect(f.app.pins).toEqual({});
    expect(solves[solves.length - 1]['edition_pins']).toBeUndefined();
    expect(reply(f)).toContain(MESSAGES.en.askPinsNotPossible);
  });

  it('compound: applies in order and shows one line per reply', async () => {
    askReply = () => ok(
      [act('exclude_store', { store_id: 'amazon_de' }), act('set_tab', { tab: 'one' })],
      [{ reply_key: 'askDoneExclude', reply_args: { shop: 'Amazon.de' } }, { reply_key: 'askDoneTab', reply_args: { tab: 'one' } }],
    );
    const f = await setup();
    await ask(f, 'no Amazon and one order');
    expect(f.app.tab).toBe('one');
    expect(f.app.selected).toEqual(['libris', 'emag']);
    const lines = Array.from(f.el.querySelectorAll('app-ask-box .ask-reply span')).map((s) => s.textContent);
    expect(lines).toEqual(['Left out Amazon.de.', 'Showing 1 order.']);
  });

  it('an action outside the five: nothing applied, askUnsupported', async () => {
    askReply = () => ok([act('delete_basket', {})]);
    const f = await setup();
    const before = solves.length;
    await ask(f, 'delete it');
    expect(reply(f)).toBe(MESSAGES.en.askUnsupported);
    expect(solves.length).toBe(before);
  });

  it('include_store of an unselectable shop puts it back in selected and the request', async () => {
    (window as unknown as { __unsel?: string }).__unsel = 'amazon_de';
    askReply = () => ok([act('include_store', { store_id: 'amazon_de' })]);
    const f = await setup();
    await ask(f, 'include Amazon');
    expect(f.app.selected).toEqual(['libris', 'emag', 'amazon_de']);
    expect(solves[solves.length - 1]['selected_store_ids']).toEqual(['libris', 'emag', 'amazon_de']);
    expect(f.app.tab).toBe('custom');
  });

  it('compound no Amazon and exact editions: not_possible keeps the exclude, rolls the pins back, shows askPinsNotPossible', async () => {
    (window as unknown as { __np?: boolean }).__np = true;
    askReply = () => ok(
      [act('exclude_store', { store_id: 'amazon_de' }), act('pin_editions', { mode: 'current' })],
      [{ reply_key: 'askDoneExclude', reply_args: { shop: 'Amazon.de' } }, { reply_key: 'askDonePinned', reply_args: {} }],
    );
    const f = await setup();
    await ask(f, 'no Amazon and exact editions');
    expect(f.app.selected).toEqual(['libris', 'emag']);
    expect(f.app.tab).toBe('custom');
    expect(f.app.pins).toEqual({});
    expect(solves[solves.length - 1]['selected_store_ids']).toEqual(['libris', 'emag']);
    expect(solves[solves.length - 1]['edition_pins']).toBeUndefined();
    expect(reply(f)).toContain(MESSAGES.en.askPinsNotPossible);
    expect(reply(f)).toContain('Left out Amazon.de.');
  });

  it('a reply where every action is ignored applies nothing and shows askUnsupported', async () => {
    askReply = () => ok([act('delete_basket', {}), act('set_tab', { tab: 'bogus' }), act('exclude_store', { store_id: 'nowhere' })]);
    const f = await setup();
    const before = solves.length;
    const tab = f.app.tab;
    await ask(f, 'nonsense');
    expect(solves.length).toBe(before);
    expect(f.app.tab).toBe(tab);
    expect(f.app.selected).toBeNull();
    expect(f.app.pins).toEqual({});
    expect(reply(f)).toBe(MESSAGES.en.askUnsupported);
  });

  it('server unsupported -> askUnsupported; 422 -> askUnsupported', async () => {
    askReply = () => new Response(JSON.stringify({ status: 'unsupported', actions: [], reply_key: 'askUnsupported', reply_args: {} }), { status: 200 });
    const f = await setup();
    await ask(f, 'make me a sandwich');
    expect(reply(f)).toBe(MESSAGES.en.askUnsupported);
    askReply = () => new Response('{}', { status: 422 });
    await ask(f, 'again');
    expect(reply(f)).toBe(MESSAGES.en.askUnsupported);
  });

  it('429 -> askBusy; budget refusal -> askUnavailable', async () => {
    askReply = () => new Response('{}', { status: 429 });
    const f = await setup();
    await ask(f, 'one order');
    expect(reply(f)).toBe(MESSAGES.en.askBusy);
    askReply = () => new Response(JSON.stringify({ status: 'unsupported', actions: [], reply_key: 'askUnavailable', reply_args: {} }), { status: 200 });
    await ask(f, 'one order');
    expect(reply(f)).toBe(MESSAGES.en.askUnavailable);
  });

  it('renders in Romanian from the lang input', async () => {
    const f = await setup();
    f.app.lang = 'ro';
    f.fixture.detectChanges();
    expect(f.el.querySelector('app-ask-box .ask-title')!.textContent).toBe(MESSAGES.ro.askTitle);
    f.app.lang = 'en';
  });

  it('is hidden in fixture mode', async () => {
    const f = await setup();
    f.app.fixture = 'failed-read';
    f.fixture.detectChanges();
    expect(f.el.querySelector('app-ask-box input')).toBeNull();
  });
});
