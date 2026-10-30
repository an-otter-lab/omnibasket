import { ComponentFixture, TestBed } from '@angular/core/testing';
import { AppComponent } from './app.component';
import { MembershipsComponent } from './memberships.component';
import { MEMBERSHIPS_KEY, MembershipRow, formatAmount, formatReadDate, loadDeclared } from './memberships';
import { MESSAGES } from './messages';

// The two rows /solve returns for ro-v1 (data/shops/*.yaml, Spike 3, read 30 Oct 2026).
const PRIME: MembershipRow = {
  id: 'amazon_prime',
  store_id: 'amazon_de',
  store_name: 'Amazon.de',
  name: 'Amazon Prime',
  effect: 'none',
  read_status: 'read',
  declared: false,
  changes_totals: false,
  source_url: 'https://www.amazon.de/gp/help/customer/display.html?nodeId=GZXW7X6AKTHNUP6H',
  read_date: '2026-10-30',
  evidence: 'Romania block: Standardzustellung, Mindestbestellwert 49 €',
  member_threshold_cents: null,
  store_threshold_cents: 26217,
  store_currency: 'RON',
  everyone_rule: {
    amount_cents: 4900,
    currency: 'EUR',
    source_url: 'https://www.amazon.de/gp/help/customer/display.html?nodeId=GZXW7X6AKTHNUP6H',
    read_date: '2026-10-28',
  },
};
const GENIUS: MembershipRow = {
  id: 'emag_genius',
  store_id: 'emag',
  store_name: 'eMAG',
  name: 'eMAG Genius',
  effect: 'unknown',
  read_status: 'refused',
  declared: false,
  changes_totals: false,
  source_url: 'https://www.emag.ro/genius',
  read_date: '2026-10-30',
  evidence: 'HTTP 511, eMAG Captcha',
  member_threshold_cents: null,
  store_threshold_cents: null,
  store_currency: null,
  everyone_rule: null,
};
const ROWS = [PRIME, GENIUS];
const NEW_KEYS = Object.keys(MESSAGES.en).filter((k) => k.startsWith('membership') || k === 'monthsShort');

function render(lang: 'en' | 'ro' = 'en', declared: string[] = []): ComponentFixture<MembershipsComponent> {
  const fixture = TestBed.createComponent(MembershipsComponent);
  fixture.componentRef.setInput('rows', ROWS);
  fixture.componentRef.setInput('declared', declared);
  fixture.componentRef.setInput('lang', lang);
  fixture.detectChanges();
  return fixture;
}

function el(fixture: ComponentFixture<unknown>): HTMLElement {
  return fixture.nativeElement as HTMLElement;
}

function box(fixture: ComponentFixture<unknown>, id: string): HTMLInputElement {
  return el(fixture).querySelector<HTMLInputElement>(`[data-membership="${id}"] input`)!;
}

function note(fixture: ComponentFixture<unknown>, id: string): HTMLElement | null {
  return el(fixture).querySelector<HTMLElement>(`[data-membership-note="${id}"]`);
}

describe('memberships (feature 5)', () => {
  beforeEach(() => localStorage.removeItem(MEMBERSHIPS_KEY));
  afterEach(() => localStorage.removeItem(MEMBERSHIPS_KEY));

  it('shows one toggle per membership, off, with no note', () => {
    const f = render();
    expect(el(f).querySelector('[data-membership="amazon_prime"]')!.textContent!.trim()).toBe('I have Amazon Prime');
    expect(el(f).querySelector('[data-membership="emag_genius"]')!.textContent!.trim()).toBe('I have eMAG Genius');
    expect(box(f, 'amazon_prime').checked).toBeFalse();
    expect(note(f, 'amazon_prime')).toBeNull();
    expect(note(f, 'emag_genius')).toBeNull();
  });

  it('Prime: the note names 49 € and 262,17 lei for everyone, with the source and read date', () => {
    const f = render();
    let emitted: string[] | null = null;
    f.componentInstance.declaredChange.subscribe((ids) => (emitted = ids));
    box(f, 'amazon_prime').click();
    f.detectChanges();
    expect(emitted!).toEqual(['amazon_prime']);
    expect(loadDeclared()).toEqual(['amazon_prime']);
    const n = note(f, 'amazon_prime')!;
    expect(n.querySelector('p')!.textContent!.trim()).toBe(
      'Amazon Prime does not change delivery to Romania. Free delivery to Romania starts at 49 € (262,17 lei) for everyone, Amazon Prime members included. Your totals do not change.',
    );
    const link = n.querySelector<HTMLAnchorElement>('a')!;
    expect(link.getAttribute('href')).toBe(PRIME.source_url);
    expect(link.textContent!.trim()).toBe('Source: ' + PRIME.source_url + ', read 30 Oct 2026');
  });

  it('Genius: "rules not printed", nothing invented, read attempt dated', () => {
    const f = render('en', ['emag_genius']);
    expect(box(f, 'emag_genius').checked).toBeTrue();
    const n = note(f, 'emag_genius')!;
    expect(n.querySelector('p')!.textContent!.trim()).toBe(
      'eMAG Genius: rules not printed. The eMAG rules page could not be read, so nothing is assumed. Your totals do not change.',
    );
    expect(n.textContent).not.toMatch(/\d+,\d\d lei/);
    expect(n.querySelector('a')!.textContent!.trim()).toBe('Read tried: https://www.emag.ro/genius, 30 Oct 2026');
  });

  it('RO: Prime and Genius notes', () => {
    const f = render('ro', ['amazon_prime', 'emag_genius']);
    expect(el(f).querySelector('[data-membership="amazon_prime"]')!.textContent!.trim()).toBe('Am Amazon Prime');
    expect(note(f, 'amazon_prime')!.querySelector('p')!.textContent!.trim()).toBe(
      'Amazon Prime nu schimbă livrarea în România. Livrarea gratuită în România începe de la 49 € (262,17 lei) pentru toată lumea, inclusiv pentru membrii Amazon Prime. Totalurile nu se schimbă.',
    );
    expect(note(f, 'amazon_prime')!.querySelector('a')!.textContent!.trim()).toBe(
      'Sursa: ' + PRIME.source_url + ', citită pe 30 oct. 2026',
    );
    expect(note(f, 'emag_genius')!.querySelector('p')!.textContent!.trim()).toBe(
      'eMAG Genius: regulile nu sunt afișate. Pagina de reguli eMAG nu a putut fi citită, așa că nu presupunem nimic. Totalurile nu se schimbă.',
    );
    expect(note(f, 'emag_genius')!.querySelector('a')!.textContent!.trim()).toBe(
      'Citire încercată: https://www.emag.ro/genius, pe 30 oct. 2026',
    );
  });

  it('toggling off removes the note and the stored id', () => {
    const f = render('en', ['amazon_prime']);
    box(f, 'amazon_prime').click();
    f.detectChanges();
    expect(note(f, 'amazon_prime')).toBeNull();
    expect(loadDeclared()).toEqual([]);
  });

  it('formats printed amounts and read dates', () => {
    expect(formatAmount(4900, 'EUR')).toBe('49 €');
    expect(formatAmount(899, 'EUR')).toBe('8,99 €');
    expect(formatReadDate('2026-10-30', 'en')).toBe('30 Oct 2026');
    expect(formatReadDate('2026-10-30', 'ro')).toBe('30 oct. 2026');
    expect(MESSAGES.en.monthsShort.split(' ').length).toBe(12);
    expect(MESSAGES.ro.monthsShort.split(' ').length).toBe(12);
  });

  it('keeps the new copy on comma-below ș/ț, order/comandă, never parcel/colet, in RO and EN', () => {
    expect(NEW_KEYS.length).toBe(11);
    for (const lang of ['en', 'ro'] as const) {
      const text = NEW_KEYS.map((k) => (MESSAGES[lang] as unknown as Record<string, string>)[k]).join(' ');
      expect(text.trim().length).toBeGreaterThan(0);
      expect(/[\u015E\u015F\u0162\u0163]/.test(text)).toBeFalse();
      expect(/parcel|colet/i.test(text)).toBeFalse();
    }
    expect(MESSAGES.ro.membershipUnknown).toContain('\u0219');
  });
});

describe('memberships in the result controls', () => {
  let bodies: Record<string, unknown>[];

  beforeEach(() => {
    localStorage.removeItem(MEMBERSHIPS_KEY);
    bodies = [];
    const payload = {
      currency: 'RON',
      cached: true,
      read_at_range: { oldest: '2026-10-28', newest: '2026-10-28' },
      degraded: null,
      shops: [],
      books: [],
      failed_reads: [],
      memberships: ROWS,
      cheapest: { status: 'ranked', reason: null, total_cents: 51516, books_subtotal_cents: 0, order_count: 2, orders: [], delta_vs_cheapest_cents: 0, not_ranked: [] },
      one_parcel: { status: 'ranked', reason: null, best_store_id: null, answer: null, per_book_delta: [], shops: [] },
      custom: null,
      edition: { pins: {}, unknown_pins: [], status: 'ranked', reason: null, unpinned_total_cents: null, total_cents: null, delta_cents: null, not_ranked: [] },
    };
    spyOn(window, 'fetch').and.callFake(async (url: RequestInfo | URL, init?: RequestInit) => {
      if (String(url).endsWith('/why')) {
        return new Response(JSON.stringify({ text: 'Fallback explanation.', source: 'template' }), { status: 200 });
      }
      bodies.push(JSON.parse(String(init?.body || '{}')));
      return new Response(JSON.stringify(payload), { status: 200 });
    });
  });
  afterEach(() => localStorage.removeItem(MEMBERSHIPS_KEY));

  it('renders the toggles on the result and re-solves with the declared ids', async () => {
    const fixture = TestBed.createComponent(AppComponent);
    await fixture.componentInstance.load();
    fixture.componentInstance.route = { name: 'result', arg: '' };
    fixture.componentInstance.tab = 'cheapest';
    fixture.detectChanges();
    expect(el(fixture).querySelector('app-memberships [data-membership="amazon_prime"]')).not.toBeNull();
    expect(bodies.every((b) => !('memberships' in b))).toBeTrue();
    el(fixture).querySelector<HTMLInputElement>('[data-membership="amazon_prime"] input')!.click();
    await fixture.whenStable();
    expect(bodies[bodies.length - 1]['memberships']).toEqual(['amazon_prime']);
  });

  it('restores declared memberships from localStorage and drops unknown ids', async () => {
    localStorage.setItem(MEMBERSHIPS_KEY, JSON.stringify(['emag_genius', 'gone_club']));
    const fixture = TestBed.createComponent(AppComponent);
    await fixture.componentInstance.load();
    expect(fixture.componentInstance.declaredMemberships).toEqual(['emag_genius']);
    expect(bodies[bodies.length - 1]['memberships']).toEqual(['emag_genius']);
  });
});
