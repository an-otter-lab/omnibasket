// Feature 7: Ask Omnibasket. The pure half: turns the server's closed action list into the
// UI fields it drives. No DOM, no fetch. The server validates too; this re-checks, because the
// server could be a stale build: anything outside the five names, or naming a shop (or
// membership) that is not in the current answer, is ignored and counted.

export type AskTab = 'cheapest' | 'one' | 'custom';

export interface AskUiState {
  tab: AskTab;
  selected: string[] | null;
  memberships: string[];
  pins: Record<string, string>;
  /** Shops in the current /solve. */
  stores: string[];
  /** Shops a custom selection starts from when none is chosen yet: the ones the solver can price. Defaults to stores. */
  base?: string[];
  /** Membership ids the current /solve knows. */
  membershipIds: string[];
  /** item_id -> edition of the offer the current tab's answer chose (books with no known edition absent). */
  chosen: Record<string, string>;
}

export interface AskNext {
  tab: AskTab;
  selected: string[] | null;
  memberships: string[];
  pins: Record<string, string>;
  /** Actions that were not one of the five, or named an id that is not in the current answer. */
  ignored: number;
}

const TABS: readonly string[] = ['cheapest', 'one', 'custom'];

function isObj(v: unknown): v is Record<string, unknown> {
  return !!v && typeof v === 'object' && !Array.isArray(v);
}

export function applyActions(actions: unknown, ui: AskUiState): AskNext {
  const next: AskNext = { tab: ui.tab, selected: ui.selected ? [...ui.selected] : null, memberships: [...ui.memberships], pins: { ...ui.pins }, ignored: 0 };
  for (const raw of Array.isArray(actions) ? actions : []) {
    const a = isObj(raw) ? raw : {};
    const args = isObj(a['args']) ? a['args'] : {};
    switch (a['name']) {
      case 'set_tab':
        if (typeof args['tab'] === 'string' && TABS.includes(args['tab'])) next.tab = args['tab'] as AskTab;
        else next.ignored++;
        break;
      case 'exclude_store':
      case 'include_store': {
        const id = args['store_id'];
        if (typeof id !== 'string' || !ui.stores.includes(id)) { next.ignored++; break; }
        const cur = next.selected ?? [...(ui.base ?? ui.stores)];
        if (a['name'] === 'exclude_store') {
          const rest = cur.filter((s) => s !== id);
          if (!rest.length) { next.ignored++; break; }
          next.selected = rest;
        } else {
          next.selected = cur.includes(id) ? cur : [...cur, id];
        }
        next.tab = 'custom';
        break;
      }
      case 'set_membership': {
        const id = args['membership_id'];
        if (typeof id !== 'string' || !ui.membershipIds.includes(id) || typeof args['on'] !== 'boolean') { next.ignored++; break; }
        const rest = next.memberships.filter((m) => m !== id);
        next.memberships = args['on'] ? [...rest, id] : rest;
        break;
      }
      case 'pin_editions':
        if (args['mode'] === 'current') next.pins = { ...ui.chosen };
        else if (args['mode'] === 'clear') next.pins = {};
        else next.ignored++;
        break;
      default:
        next.ignored++;
    }
  }
  return next;
}

/** Structural view of the /solve payload: only what Ask reads. */
export interface AskData {
  shops: { store_id: string; selectable?: boolean; books_listed?: number }[];
  books: { item_id: string; editions: { edition: string }[]; shops?: { store_id: string; price_cents?: number | null }[] }[];
  memberships?: { id: string; store_id?: string; name?: string }[];
  cheapest: { orders?: AskOrder[] };
  one_order: { answer: { orders?: AskOrder[] } | null };
  custom: { orders?: AskOrder[] } | null;
}
interface AskOrder { store_id?: string; books: { item_id: string; edition: string | null }[] }

export interface AskInputs { tab: AskTab; selected: string[] | null; pins: Record<string, string>; memberships: string[] }

export function uiState(data: AskData, cur: AskInputs): AskUiState {
  const orders = (cur.tab === 'one' ? data.one_order.answer?.orders : cur.tab === 'custom' ? data.custom?.orders : data.cheapest.orders) || [];
  const chosen: Record<string, string> = {};
  for (const o of orders) for (const b of o.books) if (b.edition) chosen[b.item_id] = b.edition;
  // every shop with an offer in this basket, whether or not the plan lists it as a shop row
  const offered = data.books.flatMap((b) => (b.shops || []).filter((o) => o.price_cents != null).map((o) => o.store_id));
  const stores = [...new Set([...data.shops.map((s) => s.store_id), ...offered])];
  return { ...cur, stores, base: data.shops.filter((s) => s.selectable !== false).map((s) => s.store_id), membershipIds: (data.memberships || []).map((m) => m.id), chosen };
}

/** The /ask request body's state (the server contract's AskState). */
export function askState(data: AskData, cur: AskInputs): Record<string, unknown> {
  const ui = uiState(data, cur);
  return {
    tab: cur.tab,
    selected_store_ids: cur.selected,
    memberships: cur.memberships,
    edition_pins: cur.pins,
    store_ids: ui.stores,
    membership_ids: ui.membershipIds,
    items: data.books.map((b) => ({ item_id: b.item_id, editions: b.editions.map((e) => e.edition), store_ids: [...new Set((b.shops || []).filter((o) => o.price_cents != null).map((o) => o.store_id))] })),
  };
}
