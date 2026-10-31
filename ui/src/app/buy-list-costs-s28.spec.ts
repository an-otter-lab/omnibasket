import { ComponentFixture, TestBed } from '@angular/core/testing';
import { BuyListComponent } from './buy-list.component';
import { OrderLike, buyListFromOrders, decodeBuyList, encodeBuyList } from './buy-list';

// S28: each shop on the buy list shows the delivery (or "Free") and the order total from the result.
const LIBRIS: OrderLike = {
  store_id: 'libris',
  books: [{ title: 'Matilda', price_cents: 3990, listing_url: 'https://www.libris.ro/carte/matilda/1' }],
  delivery_known: true,
  delivery_cents: 1499,
  order_fee_cents: 0,
  order_total_cents: 5489,
};
const BX_FREE: OrderLike = {
  store_id: 'books_express',
  books: [{ title: 'The BFG', price_cents: 21000, listing_url: 'https://www.books-express.ro/bfg/p/x,9780142410387' }],
  delivery_known: true,
  delivery_cents: 0,
  order_fee_cents: 0,
  order_total_cents: 21000,
};
const AMAZON_UNKNOWN: OrderLike = {
  store_id: 'amazon_de',
  books: [{ title: 'Owl Babies', price_cents: 5178, listing_url: 'https://www.amazon.de/dp/0744531675' }],
  delivery_known: false,
  delivery_cents: null,
  order_fee_cents: null,
  order_total_cents: null,
};

function render(code: string, lang: 'en' | 'ro' = 'en'): HTMLElement {
  const fixture: ComponentFixture<BuyListComponent> = TestBed.createComponent(BuyListComponent);
  fixture.componentRef.setInput('lang', lang);
  fixture.componentRef.setInput('code', code);
  fixture.detectChanges();
  return fixture.nativeElement as HTMLElement;
}

const costs = (el: HTMLElement, shop: string) =>
  Array.from(el.querySelectorAll(`[data-shop="${shop}"] [data-costs] .row > *`))
    .map((c) => (c.textContent || '').trim())
    .join(' ');

describe('S28: the buy list shows delivery and the order total', () => {
  beforeEach(() => localStorage.clear());

  it('shows the delivery and the total per shop, as the result did', () => {
    const el = render(encodeBuyList(buyListFromOrders([LIBRIS])));
    expect(costs(el, 'libris')).toBe('Delivery 14,99 lei Order total 54,89 lei');
  });

  it('a free delivery says Free (RO: Gratuită)', () => {
    const code = encodeBuyList(buyListFromOrders([BX_FREE]));
    expect(costs(render(code), 'books_express')).toBe('Delivery Free Order total 210,00 lei');
    expect(costs(render(code, 'ro'), 'books_express')).toBe('Livrare Gratuită Totalul comenzii 210,00 lei');
  });

  it('a delivery the shop does not print says so, with no total', () => {
    const el = render(encodeBuyList(buyListFromOrders([AMAZON_UNKNOWN])));
    expect(costs(el, 'amazon_de')).toBe('Delivery not printed Order total no total');
  });

  it('an order fee is its own row only when there is one', () => {
    const el = render(encodeBuyList(buyListFromOrders([{ ...LIBRIS, order_fee_cents: 500, order_total_cents: 5989 }])));
    expect(costs(el, 'libris')).toBe('Delivery 14,99 lei Order fee 5,00 lei Order total 59,89 lei');
  });

  it('the costs travel in the share link; a link from before S28 still opens, without them', () => {
    const shops = decodeBuyList(encodeBuyList(buyListFromOrders([LIBRIS, BX_FREE])))!;
    expect(shops.map((s) => s.costs)).toEqual([
      { delivery_cents: 1499, fee_cents: 0, total_cents: 5489 },
      { delivery_cents: 0, fee_cents: 0, total_cents: 21000 },
    ]);
    const old = encodeBuyList([{ store_id: 'libris', books: [{ title: 'Matilda', price_cents: 3990, listing_url: null }] }]);
    const el = render(old);
    expect(el.querySelector('[data-shop="libris"]')).not.toBeNull();
    expect(el.querySelector('[data-costs]')).toBeNull();
  });

  it('a crafted cost is refused like any other bad field', () => {
    const bad = btoa(JSON.stringify([1, [['libris', [['Matilda', 3990, null]], -5, 0, 100]]])).replace(/=+$/, '');
    expect(decodeBuyList(bad)).toBeNull();
    const text = btoa(JSON.stringify([1, [['libris', [['Matilda', 3990, null]], 'x', 0, 100]]])).replace(/=+$/, '');
    expect(decodeBuyList(text)).toBeNull();
  });
});
