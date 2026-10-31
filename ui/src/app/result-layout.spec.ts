import { TestBed } from '@angular/core/testing';
import { By } from '@angular/platform-browser';
import { demoSample } from './demo-sample';
import { AppComponent } from './app.component';
import { AskBoxComponent } from './ask-box.component';
import { BasketService } from './basket.service';
import { MEMBERSHIPS_KEY, MembershipRow } from './memberships';

// R10: the result's dead controls. A membership for a shop with no book in the basket is
// hidden; the editions control exists only when a book has a second edition; a locked
// custom switch says which book it is the only shop for.

const GENIUS: MembershipRow = {
  id: 'emag_genius', store_id: 'emag', store_name: 'eMAG', name: 'eMAG Genius',
  effect: 'unknown', read_status: 'refused', declared: false, changes_totals: false,
  source_url: 'https://www.emag.ro/genius', read_date: '2026-10-30', evidence: 'captcha',
  member_threshold_cents: null, store_threshold_cents: null, store_currency: null, everyone_rule: null,
};
const PRIME: MembershipRow = {
  ...GENIUS, id: 'amazon_prime', store_id: 'amazon_de', store_name: 'Amazon.de', name: 'Amazon Prime',
  effect: 'none', read_status: 'read', source_url: 'https://www.amazon.de/prime',
};

interface ShopIn {
  store_id: string;
  selectable?: boolean;
  books_listed?: number;
}

function shop(s: ShopIn) {
  return {
    store_id: s.store_id, currency: 'RON', priced: true, excluded: false,
    selectable: s.selectable !== false, not_selectable_code: null, not_selectable_reason: null,
    read_at: null, books_listed: s.books_listed ?? 1, failed_reads: [],
    free_delivery_threshold_cents: 13500, delivery_cents: 1290, delivery_known: true, order_fee_cents: 0,
  };
}

const ORDER = {
  store_id: 'libris',
  books: [{ item_id: 'a', title: 'Harry Potter', isbn13: '9781526605412', edition: null, price_cents: 5000, seller_certainty: 'direct', listing_url: 'https://www.libris.ro/x', read_at: null }],
  books_subtotal_cents: 5000, qualifying_cents: 5000, free_delivery_threshold_cents: 13500,
  threshold_crossed: false, over_under_threshold_cents: -8500, short_of_threshold_cents: 8500,
  delivery_known: true, delivery_cents: 1290, order_fee_cents: 0, order_total_cents: 6290, read_at: null,
};

function payload(opts: { editions: boolean; shops: ShopIn[] }) {
  const book = {
    item_id: 'a', title: 'Harry Potter', isbn13: '9781526605412', edition_pin: null,
    editions: opts.editions
      ? [{ edition: 'paperback', cheapest_price_cents: 5000, store_ids: ['libris'] }, { edition: 'hardcover', cheapest_price_cents: 7000, store_ids: ['libris'] }]
      : [],
    assigned_store_id: 'libris',
    shops: [{ store_id: 'libris', status: 'in_plan', price_cents: 5000, seller_certainty: 'direct', edition: null }],
  };
  return {
    currency: 'RON', cached: true, read_at_range: { oldest: '2026-10-30', newest: '2026-10-30' },
    degraded: null,
    shops: opts.shops.map(shop),
    books: [book],
    failed_reads: [],
    memberships: [GENIUS, PRIME],
    cheapest: { status: 'ranked', reason: null, total_cents: 6290, books_subtotal_cents: 5000, order_count: 1, orders: [ORDER], delta_vs_cheapest_cents: 0, not_ranked: [] },
    ['one_' + 'parcel']: { status: 'not_possible', reason: null, best_store_id: null, answer: null, per_book_delta: [], shops: [] },
    custom: { status: 'ranked', reason: null, total_cents: 6290, books_subtotal_cents: 5000, order_count: 1, orders: [ORDER], delta_vs_cheapest_cents: 0, not_ranked: [], selected_store_ids: ['libris'], unselectable: [], moves: [] },
    edition: { pins: {}, unknown_pins: [], status: 'ranked', reason: null, unpinned_total_cents: null, total_cents: null, delta_cents: null, not_ranked: [] },
  };
}

async function render(opts: { editions: boolean; shops: ShopIn[]; ask?: unknown[]; solves?: Record<string, unknown>[] }) {
  demoSample();
  const body = payload(opts);
  spyOn(window, 'fetch').and.callFake(async (url: RequestInfo | URL, init?: RequestInit) => {
    const u = String(url);
    if (u.endsWith('/why')) return new Response(JSON.stringify({ text: 'Sentence.', source: 'template' }), { status: 200 });
    if (u.endsWith('/ask')) {
      return new Response(JSON.stringify({ status: 'ok', actions: opts.ask ?? [], reply_key: 'askDoneMembership', reply_args: { name: 'eMAG Genius' } }), { status: 200 });
    }
    if (u.endsWith('/solve')) (opts.solves ?? []).push(JSON.parse(String(init?.body || '{}')) as Record<string, unknown>);
    return new Response(JSON.stringify(body), { status: 200 });
  });
  const fixture = TestBed.createComponent(AppComponent);
  await fixture.componentInstance.load();
  fixture.componentInstance.route = { name: 'result', arg: '' };
  fixture.componentInstance.tab = 'cheapest';
  fixture.detectChanges();
  await fixture.whenStable();
  return fixture;
}

describe('result dead controls (R10)', () => {
  it('hides the editions control when no book has a second edition', async () => {
    const el = (await render({ editions: false, shops: [{ store_id: 'libris' }] })).nativeElement as HTMLElement;
    expect(el.querySelector('[data-editions-row]')).toBeNull();
  });

  it('shows the editions control when a book has a second edition', async () => {
    const el = (await render({ editions: true, shops: [{ store_id: 'libris' }] })).nativeElement as HTMLElement;
    expect(el.querySelector('[data-editions-row]')).not.toBeNull();
    expect(el.querySelector('[data-editions-row] a')!.getAttribute('href')).toBe('#/editions');
  });

  it('shows a membership only for a shop that can take a book', async () => {
    const none = (await render({ editions: false, shops: [{ store_id: 'libris' }] })).nativeElement as HTMLElement;
    expect(none.querySelectorAll('app-memberships [data-membership]').length).toBe(0);
    const emag = (await render({ editions: false, shops: [{ store_id: 'libris' }, { store_id: 'emag' }] })).nativeElement as HTMLElement;
    const rows = emag.querySelectorAll('app-memberships [data-membership]');
    expect(rows.length).toBe(1);
    expect(rows[0].getAttribute('data-membership')).toBe('emag_genius');
  });

  it('says why the last chosen shop cannot be switched off', async () => {
    const fixture = await render({ editions: false, shops: [{ store_id: 'libris' }] });
    const app = fixture.componentInstance;
    app.tab = 'custom';
    fixture.detectChanges();
    const reason = app.lockedReason((app.data!.shops[0] as never));
    expect(reason).toBe('Only shop with Harry Potter');
    const desc = (fixture.nativeElement as HTMLElement).querySelector('[data-shop-switch="libris"] input')!.getAttribute('aria-describedby');
    expect(desc).toContain('libris');
  });

  it('offers the membership ask chip only when that shop can take a book, and the chip acts', async () => {
    localStorage.removeItem(MEMBERSHIPS_KEY);
    const none = (await render({ editions: false, shops: [{ store_id: 'libris' }] })).nativeElement as HTMLElement;
    const noneChips = Array.from(none.querySelectorAll('app-ask-box .ask-chips .chip')).map((c) => c.textContent!.trim());
    expect(noneChips).toEqual([]); // S11: one shop, already one order and no Amazon: no example would change the answer
    expect(noneChips.some((t) => t.includes('Genius'))).toBeFalse();

    const solves: Record<string, unknown>[] = [];
    const fixture = await render({ editions: false, shops: [{ store_id: 'libris' }, { store_id: 'emag' }], ask: [{ name: 'set_membership', args: { membership_id: 'emag_genius', on: true } }], solves });
    const el = fixture.nativeElement as HTMLElement;
    const chip = Array.from(el.querySelectorAll<HTMLButtonElement>('app-ask-box .ask-chips .chip')).find((c) => c.textContent!.includes('Genius'));
    expect(chip).not.toBeUndefined();
    expect(chip!.textContent!.trim()).toBe('I have eMAG Genius');

    chip!.click();
    const box = fixture.debugElement.query(By.directive(AskBoxComponent)).componentInstance as AskBoxComponent;
    for (let i = 0; i < 200 && (box.working || box.busy || fixture.componentInstance.busy); i++) { await new Promise((r) => setTimeout(r, 10)); fixture.detectChanges(); }
    expect(solves.some((s) => Array.isArray(s['memberships']) && (s['memberships'] as string[]).includes('emag_genius'))).toBeTrue();
    expect(fixture.componentInstance.declaredMemberships).toContain('emag_genius');
    expect(el.querySelector<HTMLInputElement>('app-memberships [data-membership="emag_genius"] input')!.checked).toBeTrue();
  });
});

// S31 + S32: "Your books, shop by shop" sits in the left column under the order cards, and the
// header book count on the result page jumps to it instead of linking to the page it is on.
describe('S31/S32: your books under the cards; the header count jumps there', () => {
  async function withBasket() {
    const fixture = await render({ editions: false, shops: [{ store_id: 'libris' }] });
    const app = fixture.componentInstance;
    app.sampleMode = false;
    const svc = TestBed.inject(BasketService);
    svc.addFromLive({ books: [{ item_id: 'a', title: 'Harry Potter', isbn13: '9781526605412', shops: [] }], joined_item_id: 'a' }, '9781526605412', 'Harry Potter');
    fixture.detectChanges();
    return fixture;
  }
  afterEach(() => localStorage.clear());

  it('S31: the section is in the left column, right after the order cards, once', async () => {
    const el = (await withBasket()).nativeElement as HTMLElement;
    const sections = el.querySelectorAll('[data-section="your-books"]');
    expect(sections.length).toBe(1);
    const books = sections[0];
    expect(books.closest('.rmain')).not.toBeNull();
    expect(books.closest('.rside')).toBeNull();
    expect(books.parentElement!.previousElementSibling!.classList).toContain('rcards');
  });

  it('S32: on the result page the count chip jumps to Your books and does not navigate', async () => {
    const fixture = await withBasket();
    const app = fixture.componentInstance;
    const go = spyOn(app, 'go');
    const el = fixture.nativeElement as HTMLElement;
    document.body.appendChild(el);
    try {
      const books = el.querySelector<HTMLElement>('[data-section="your-books"]')!;
      const scroll = spyOn(books, 'scrollIntoView');
      el.querySelector<HTMLAnchorElement>('[data-header-count]')!.click();
      expect(go).not.toHaveBeenCalled();
      expect(scroll).toHaveBeenCalled();
      expect(document.activeElement!.id).toBe('yb-h');
    } finally {
      el.remove();
    }
  });

  it('S32: off the result page the count chip still opens the result', async () => {
    const fixture = await withBasket();
    const app = fixture.componentInstance;
    const go = spyOn(app, 'go');
    app.route = { name: 'add', arg: '' };
    app.onCountClick(new MouseEvent('click', { cancelable: true }));
    expect(go).toHaveBeenCalledWith('result');
  });
});

// S33: a basket book that is in none of the orders is named next to them, with why, and links to its row.
describe('S33: a left-out book is named next to the orders', () => {
  const SAPIENS = '9786063373671';
  const OTHER = '9789734668465';
  async function withBasket(extra: { isbn: string; title: string; priced: boolean }[], lang: 'en' | 'ro' = 'en') {
    const fixture = await render({ editions: false, shops: [{ store_id: 'libris' }] });
    const app = fixture.componentInstance;
    app.sampleMode = false;
    app.lang = lang;
    const svc = TestBed.inject(BasketService);
    svc.addFromLive({ books: [{ item_id: 'a', title: 'Harry Potter', isbn13: '9781526605412', shops: [] }], joined_item_id: 'a' }, '9781526605412', 'Harry Potter');
    for (const b of extra) {
      const shops = b.priced ? [{ store_id: 'emag', price_cents: 4000 }] : [];
      svc.addFromLive({ books: [{ item_id: 'x' + b.isbn, title: b.title, isbn13: b.isbn, shops }], joined_item_id: 'x' + b.isbn }, b.isbn, b.title);
    }
    fixture.detectChanges();
    return fixture;
  }
  afterEach(() => localStorage.clear());

  it('names the one book that is out and says no shop we read has it', async () => {
    const el = (await withBasket([{ isbn: SAPIENS, title: 'Sapiens', priced: false }])).nativeElement as HTMLElement;
    const panel = el.querySelector('.rcards [data-left-out-books]')!;
    expect(panel).not.toBeNull();
    expect(panel.querySelector('.k')!.textContent!.trim()).toBe('1 book is not in these orders');
    const rows = panel.querySelectorAll('[data-left-out]');
    expect(rows.length).toBe(1);
    expect(rows[0].getAttribute('data-left-out')).toBe(SAPIENS);
    expect(rows[0].textContent).toContain('Sapiens');
    expect(rows[0].textContent).toContain('no shop we read has it');
    expect(rows[0].textContent).not.toContain('Harry Potter');
  });

  it('a priced book with no shop of known rules says so; two books use the plural (RO too)', async () => {
    const books = [{ isbn: SAPIENS, title: 'Sapiens', priced: false }, { isbn: OTHER, title: 'Alt titlu', priced: true }];
    const en = (await withBasket(books)).nativeElement as HTMLElement;
    expect(en.querySelector('[data-left-out-books] .k')!.textContent!.trim()).toBe('2 books are not in these orders');
    expect(en.querySelector('[data-left-out="' + OTHER + '"]')!.textContent).toContain('no shop with known delivery rules lists it');
    localStorage.clear();
    const ro = (await withBasket(books, 'ro')).nativeElement as HTMLElement;
    expect(ro.querySelector('[data-left-out-books] .k')!.textContent!.trim()).toBe('2 cărți nu sunt în aceste comenzi');
    expect(ro.querySelector('[data-left-out="' + SAPIENS + '"]')!.textContent).toContain('niciun magazin pe care l-am citit nu o are');
  });

  it('nothing is said when every basket book is in the orders', async () => {
    const el = (await withBasket([])).nativeElement as HTMLElement;
    expect(el.querySelector('[data-left-out-books]')).toBeNull();
  });

  it('the line jumps to the book row in Your books without navigating', async () => {
    const fixture = await withBasket([{ isbn: SAPIENS, title: 'Sapiens', priced: false }]);
    const go = spyOn(fixture.componentInstance, 'go');
    const el = fixture.nativeElement as HTMLElement;
    document.body.appendChild(el);
    try {
      const row = el.querySelector<HTMLElement>('[data-section="your-books"] [data-isbn="' + SAPIENS + '"]')!;
      const scroll = spyOn(row, 'scrollIntoView');
      el.querySelector<HTMLAnchorElement>('[data-left-out="' + SAPIENS + '"]')!.click();
      expect(scroll).toHaveBeenCalled();
      expect(document.activeElement).toBe(row);
      expect(go).not.toHaveBeenCalled();
    } finally {
      el.remove();
    }
  });
});
