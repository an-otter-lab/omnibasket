import { AskData, AskUiState, applyActions, askState, uiState } from './ask';

const UI: AskUiState = {
  tab: 'cheapest',
  selected: null,
  memberships: [],
  pins: {},
  stores: ['libris', 'emag', 'amazon_de'],
  membershipIds: ['emag_genius', 'amazon_prime'],
  chosen: { b1: 'paperback', b2: 'hardcover' },
};

describe('applyActions', () => {
  it('set_tab drives the tab', () => {
    expect(applyActions([{ name: 'set_tab', args: { tab: 'one' } }], UI).tab).toBe('one');
  });
  it('exclude_store drops the shop from the selection and implies custom', () => {
    const n = applyActions([{ name: 'exclude_store', args: { store_id: 'amazon_de' } }], UI);
    expect(n.selected).toEqual(['libris', 'emag']);
    expect(n.tab).toBe('custom');
  });
  it('exclude_store starts from the shops the solver can price when nothing is selected', () => {
    const n = applyActions([{ name: 'exclude_store', args: { store_id: 'amazon_de' } }], { ...UI, base: ['libris', 'amazon_de'] });
    expect(n.selected).toEqual(['libris']);
  });
  it('include_store adds the shop back', () => {
    const n = applyActions([{ name: 'include_store', args: { store_id: 'amazon_de' } }], { ...UI, tab: 'custom', selected: ['libris'] });
    expect(n.selected).toEqual(['libris', 'amazon_de']);
  });
  it('set_membership turns a membership on and off', () => {
    const on = applyActions([{ name: 'set_membership', args: { membership_id: 'emag_genius', on: true } }], UI);
    expect(on.memberships).toEqual(['emag_genius']);
    const off = applyActions([{ name: 'set_membership', args: { membership_id: 'emag_genius', on: false } }], { ...UI, memberships: ['emag_genius', 'amazon_prime'] });
    expect(off.memberships).toEqual(['amazon_prime']);
  });
  it('pin_editions current pins the chosen editions; clear empties', () => {
    expect(applyActions([{ name: 'pin_editions', args: { mode: 'current' } }], UI).pins).toEqual({ b1: 'paperback', b2: 'hardcover' });
    expect(applyActions([{ name: 'pin_editions', args: { mode: 'clear' } }], { ...UI, pins: { b1: 'paperback' } }).pins).toEqual({});
  });
  it('applies a compound in array order', () => {
    const n = applyActions([{ name: 'exclude_store', args: { store_id: 'amazon_de' } }, { name: 'set_tab', args: { tab: 'one' } }], UI);
    expect(n.tab).toBe('one');
    expect(n.selected).toEqual(['libris', 'emag']);
  });
  it('ignores names outside the five, unknown shops and memberships, bad types', () => {
    const bad = [
      { name: 'delete_basket', args: {} },
      { name: 'exclude_store', args: { store_id: 'amazon_de; drop' } },
      { name: 'set_membership', args: { membership_id: 'nope', on: true } },
      { name: 'set_membership', args: { membership_id: 'emag_genius', on: 'true' } },
      { name: 'set_tab', args: { tab: 'weird' } },
      'x',
      null,
    ];
    const n = applyActions(bad, UI);
    expect(n.ignored).toBe(bad.length);
    expect({ ...n, ignored: 0 }).toEqual({ tab: 'cheapest', selected: null, memberships: [], pins: {}, within: false, leftOut: [], ignored: 0 });
  });
  it('never excludes the last shop', () => {
    const n = applyActions([{ name: 'exclude_store', args: { store_id: 'libris' } }], { ...UI, selected: ['libris'], within: true, leftOut: ['emag', 'amazon_de'] });
    expect(n.selected).toEqual(['libris']);
    expect(n.leftOut).toEqual(['emag', 'amazon_de']);
    expect(n.ignored).toBe(1);
  });
  // T2, 3 Nov, Adrian: leaving a shop out gives the cheapest plan over the remaining shops, not the default Custom set.
  it('exclude_store makes the selection a pool to pick the cheapest from, not shops that must each take a book', () => {
    const n = applyActions([{ name: 'exclude_store', args: { store_id: 'amazon_de' } }], UI);
    expect(n.within).toBeTrue();
    expect(n.leftOut).toEqual(['amazon_de']);
  });
  it('exclude_store starts from every shop but the ones left out, not from a hand-picked Custom set', () => {
    const n = applyActions([{ name: 'exclude_store', args: { store_id: 'amazon_de' } }], { ...UI, tab: 'custom', selected: ['libris', 'amazon_de'] });
    expect(n.selected).toEqual(['libris', 'emag']);
  });
  it('a second exclude keeps the first shop out', () => {
    const first = applyActions([{ name: 'exclude_store', args: { store_id: 'amazon_de' } }], UI);
    const n = applyActions([{ name: 'exclude_store', args: { store_id: 'emag' } }], { ...UI, ...first, selected: ['libris'] });
    expect(n.selected).toEqual(['libris']);
    expect(n.leftOut).toEqual(['amazon_de', 'emag']);
  });
  it('include_store after an exclude puts the shop back in the pool and stays cheapest-over-the-pool', () => {
    const n = applyActions([{ name: 'include_store', args: { store_id: 'amazon_de' } }], { ...UI, tab: 'custom', selected: ['libris'], within: true, leftOut: ['amazon_de', 'emag'] });
    expect(n.selected).toEqual(['libris', 'amazon_de']);
    expect(n.leftOut).toEqual(['emag']);
    expect(n.within).toBeTrue();
  });
  it('include_store on a hand-picked Custom set keeps adding to it', () => {
    const n = applyActions([{ name: 'include_store', args: { store_id: 'amazon_de' } }], { ...UI, tab: 'custom', selected: ['libris'] });
    expect(n.selected).toEqual(['libris', 'amazon_de']);
    expect(n.within).toBeFalse();
  });
  it('does not mutate its input', () => {
    const ui = { ...UI, pins: { b1: 'x' } };
    applyActions([{ name: 'pin_editions', args: { mode: 'clear' } }], ui);
    expect(ui.pins).toEqual({ b1: 'x' });
  });
});

describe('askState', () => {
  const data: AskData = {
    shops: [{ store_id: 'libris' }, { store_id: 'amazon_de' }], books: [], cheapest: { orders: [] }, one_order: { answer: null }, custom: null,
  };
  it('tells the server the pool after a leave-out, and every selectable shop otherwise, never a hand-picked Custom set', () => {
    const cur = { tab: 'custom' as const, selected: ['libris'], pins: {}, memberships: [] };
    expect(askState(data, cur)['selected_store_ids']).toEqual(['libris', 'amazon_de']);
    expect(askState(data, { ...cur, within: true, leftOut: ['amazon_de'] })['selected_store_ids']).toEqual(['libris']);
  });
  it('a shop that is not selectable is not in the pool the server checks, as in applyActions', () => {
    const d: AskData = { ...data, shops: [{ store_id: 'libris' }, { store_id: 'emag', selectable: false }] };
    const cur = { tab: 'cheapest' as const, selected: null, pins: {}, memberships: [] };
    expect(askState(d, cur)['selected_store_ids']).toEqual(['libris']);
    expect(askState(d, cur)['store_ids']).toEqual(['libris', 'emag']);
    expect(applyActions([{ name: 'exclude_store', args: { store_id: 'libris' } }], uiState(d, cur)).ignored).toBe(1);
  });
});
