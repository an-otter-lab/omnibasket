import { ComponentFixture, TestBed } from '@angular/core/testing';
import { AppComponent } from './app.component';

function book(id: string, priced: boolean) {
  return {
    item_id: id, title: 'Book ' + id, isbn13: '978000000000' + id, edition_pin: null, editions: [], assigned_store_id: priced ? 'libris' : null,
    shops: priced ? [{ store_id: 'libris', status: 'in_plan', price_cents: 5000, seller_certainty: 'direct', edition: null }] : [],
  };
}

function payload(n: number) {
  const books = Array.from({ length: n }, (_, i) => book(String(i + 1), i === 0));
  return {
    currency: 'RON', cached: true, read_at_range: { oldest: '2026-10-28', newest: '2026-10-28' },
    degraded: { kind: 'one_book', reason: 'one_priced' }, shops: [], books, failed_reads: [], memberships: [],
    cheapest: { status: 'not_ranked', reason: 'one_book', total_cents: null, books_subtotal_cents: null, order_count: null, orders: [], delta_vs_cheapest_cents: null, not_ranked: [] },
    one_order: { status: 'ranked', reason: null, best_store_id: null, answer: null, per_book_delta: [], shops: [] },
    custom: null,
    edition: { pins: {}, unknown_pins: [], status: 'ranked', reason: null, unpinned_total_cents: null, total_cents: null, delta_cents: null, not_ranked: [] },
  };
}

function show(lang: 'en' | 'ro', n: number): ComponentFixture<AppComponent> {
  const f = TestBed.createComponent(AppComponent);
  const c = f.componentInstance as any;
  c.loaded = true;
  c.loading = false;
  c.sampleMode = true;
  c.sampleIds = new Set(Array.from({ length: n }, (_, i) => String(i + 1)));
  c.data = payload(n);
  c.lang = lang;
  c.route = { name: 'result', arg: '' };
  f.detectChanges();
  return f;
}

describe('one priced book in a bigger basket', () => {
  it('keeps the Ask box in the degraded state with three books', () => {
    const el = show('en', 3).nativeElement as HTMLElement;
    expect(el.querySelector('app-ask-box')).toBeTruthy();
  });

  it('says 1 of 3 books priced in EN and RO', () => {
    expect((show('en', 3).nativeElement as HTMLElement).querySelector('h1')!.textContent).toContain('1 of 3 books priced. Which shop?');
    expect((show('ro', 3).nativeElement as HTMLElement).querySelector('h1')!.textContent).toContain('1 din 3 cărți cu preț. Care magazin?');
  });

  it('keeps the old heading for a true single book', () => {
    expect((show('en', 1).nativeElement as HTMLElement).querySelector('h1')!.textContent).toContain('One book, one order. Which shop?');
    expect((show('ro', 1).nativeElement as HTMLElement).querySelector('h1')!.textContent).toContain('O carte, o comandă. Care magazin?');
  });
});
