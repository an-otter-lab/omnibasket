import { AskUiState, applyActions } from './ask';

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
    expect({ ...n, ignored: 0 }).toEqual({ tab: 'cheapest', selected: null, memberships: [], pins: {}, ignored: 0 });
  });
  it('never excludes the last shop', () => {
    const n = applyActions([{ name: 'exclude_store', args: { store_id: 'libris' } }], { ...UI, selected: ['libris'] });
    expect(n.selected).toEqual(['libris']);
    expect(n.ignored).toBe(1);
  });
  it('does not mutate its input', () => {
    const ui = { ...UI, pins: { b1: 'x' } };
    applyActions([{ name: 'pin_editions', args: { mode: 'clear' } }], ui);
    expect(ui.pins).toEqual({ b1: 'x' });
  });
});
