// Feature 5: declared memberships. The rules come from /solve (data/shops/*.yaml),
// each with its source URL and read date. Nothing here knows a shop by name.
import { formatLei } from './buy-list';
import { Lang, MESSAGES, fill } from './messages';

export type MembershipEffect = 'none' | 'unknown' | 'free_threshold';

export interface MembershipRow {
  id: string;
  store_id: string;
  store_name: string;
  name: string;
  effect: MembershipEffect;
  read_status: 'read' | 'refused';
  declared: boolean;
  changes_totals: boolean;
  source_url: string;
  read_date: string;
  evidence: string;
  member_threshold_cents: number | null;
  store_threshold_cents: number | null;
  store_currency: string | null;
  everyone_rule: { amount_cents: number; currency: string | null; source_url: string | null; read_date: string } | null;
}

export const MEMBERSHIPS_KEY = 'omnibasket.memberships.v1';

export interface ShopCandidate {
  store_id: string;
  selectable?: boolean;
  books_listed?: number;
}

/** R10: the shops that can take a book in this basket. Options rows and Ask chips share this. */
export function shopsThatTakeBooks(shops: ShopCandidate[], orders: { store_id?: string }[]): Set<string> {
  const can = new Set<string>();
  for (const s of shops) if (s.selectable || (s.books_listed ?? 0) > 0) can.add(s.store_id);
  for (const o of orders) if (o.store_id) can.add(o.store_id);
  return can;
}

export function loadDeclared(storage: Storage | null = safeStorage()): string[] {
  try {
    const raw = storage?.getItem(MEMBERSHIPS_KEY);
    const ids = raw ? JSON.parse(raw) : [];
    return Array.isArray(ids) ? ids.filter((id): id is string => typeof id === 'string') : [];
  } catch {
    return [];
  }
}

export function saveDeclared(ids: string[], storage: Storage | null = safeStorage()): void {
  try {
    storage?.setItem(MEMBERSHIPS_KEY, JSON.stringify(ids));
  } catch {
    /* private mode: the toggle still works for this page */
  }
}

function safeStorage(): Storage | null {
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

/** 2026-10-30 -> "30 Oct 2026" / "30 oct. 2026". */
export function formatReadDate(iso: string, lang: Lang): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso);
  if (!match) return iso;
  const month = MESSAGES[lang].monthsShort.split(' ')[Number(match[2]) - 1];
  return month ? `${Number(match[3])} ${month} ${match[1]}` : iso;
}

/** A printed amount: 4900 EUR -> "49 €", 4990 EUR -> "49,90 €", RON -> "… lei". */
export function formatAmount(cents: number, currency: string | null): string {
  const whole = cents % 100 === 0 ? Math.floor(cents / 100).toLocaleString('ro-RO') : formatLei(cents);
  if (currency === 'EUR') return whole + ' €';
  if (currency === 'RON') return whole + ' lei';
  return currency ? whole + ' ' + currency : whole;
}

/** The sentence the result shows for a declared membership. */
export function membershipNote(row: MembershipRow, lang: Lang): string {
  const m = MESSAGES[lang];
  if (row.effect === 'unknown') return fill(m.membershipUnknown, { name: row.name, shop: row.store_name });
  if (row.effect === 'free_threshold' && row.member_threshold_cents != null) {
    return fill(m.membershipThreshold, { name: row.name, shop: row.store_name, threshold: formatLei(row.member_threshold_cents) });
  }
  if (row.everyone_rule && row.store_threshold_cents != null) {
    return fill(m.membershipNone, {
      name: row.name,
      rule: formatAmount(row.everyone_rule.amount_cents, row.everyone_rule.currency),
      threshold: formatLei(row.store_threshold_cents),
    });
  }
  return fill(m.membershipNoneNoRule, { name: row.name });
}

export function membershipSource(row: MembershipRow, lang: Lang): string {
  const m = MESSAGES[lang];
  const template = row.read_status === 'refused' ? m.membershipSourceTried : m.membershipSourceRead;
  return fill(template, { url: row.source_url, date: formatReadDate(row.read_date, lang) });
}
