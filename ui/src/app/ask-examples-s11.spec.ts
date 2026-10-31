import { TestBed } from '@angular/core/testing';
import { AskBoxComponent } from './ask-box.component';
import { AskData, AskTab } from './ask';
import { MESSAGES } from './messages';

// S11: an Ask example is offered only when it would change the answer on the tab shown.

const order = (store_id: string, ...ids: string[]) => ({ store_id, books: ids.map((item_id) => ({ item_id, edition: null })) });
const BOOKS = [{ item_id: 'a', editions: [] }, { item_id: 'b', editions: [] }];
const SHOPS = [{ store_id: 'libris' }, { store_id: 'books_express' }];

function data(cheapest: ReturnType<typeof order>[], one: ReturnType<typeof order>[] | null): AskData {
  return { shops: SHOPS, books: BOOKS, memberships: [], cheapest: { orders: cheapest }, one_order: { answer: one ? { orders: one } : null }, custom: null };
}

function chips(d: AskData, tab: AskTab = 'cheapest', lang: 'en' | 'ro' = 'en'): string[] {
  const f = TestBed.createComponent(AskBoxComponent);
  f.componentInstance.data = d;
  f.componentInstance.tab = tab;
  f.componentInstance.lang = lang;
  f.detectChanges();
  return Array.from((f.nativeElement as HTMLElement).querySelectorAll('.ask-chips .chip')).map((c) => c.textContent!.trim());
}

describe('S11: Ask examples that fit the result', () => {
  const en = MESSAGES.en;

  it('the answer is already one order: no "Keep it to one order"', () => {
    expect(chips(data([order('libris', 'a', 'b')], [order('libris', 'a', 'b')]))).not.toContain(en.askExample1);
    expect(chips(data([order('libris', 'a'), order('books_express', 'b')], [order('libris', 'a', 'b')]), 'one')).not.toContain(en.askExample1);
  });

  it('two orders and one order is possible: "Keep it to one order" is offered', () => {
    expect(chips(data([order('libris', 'a'), order('books_express', 'b')], [order('libris', 'a', 'b')]))).toContain(en.askExample1);
    expect(chips(data([order('libris', 'a'), order('books_express', 'b')], [order('libris', 'a', 'b')]), 'cheapest', 'ro')).toContain(MESSAGES.ro.askExample1);
  });

  it('two orders but no shop has every book: one order would not answer, so it is not offered', () => {
    expect(chips(data([order('libris', 'a'), order('books_express', 'b')], null))).not.toContain(en.askExample1);
  });

  it('"No Amazon" only when Amazon.de is in the answer', () => {
    expect(chips(data([order('libris', 'a'), order('books_express', 'b')], [order('libris', 'a', 'b')]))).not.toContain(en.askExample2);
    expect(chips(data([order('libris', 'a'), order('amazon_de', 'b')], null))).toContain(en.askExample2);
  });
});
