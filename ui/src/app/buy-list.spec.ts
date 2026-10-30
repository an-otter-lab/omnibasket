import { demoSample } from './demo-sample';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { AppComponent } from './app.component';
import { BuyListComponent } from './buy-list.component';
import { buyListFromOrders, decodeBuyList, encodeBuyList, librisCartUrl, storageKey } from './buy-list';
import { MESSAGES } from './messages';

// The cheapest ro-v1 orders as /solve returns them (ui/public/fixtures/failed-read.json).
const ORDERS = [
  {
    store_id: 'amazon_de',
    books: [
      { title: 'The Boy, the Mole, the Fox and the Horse', price_cents: 11653, listing_url: 'https://www.amazon.de/dp/1529105102' },
      { title: 'Where the Wild Things Are', price_cents: 3986, listing_url: 'https://www.amazon.de/dp/0064431789' },
    ],
  },
  {
    store_id: 'libris',
    books: [
      { title: 'Ghici cât de mult te iubesc', price_cents: 5700, listing_url: 'https://www.libris.ro/carte/ghici-cat-de-mult-te-iubesc-sam-mcbratney/21197307' },
      { title: 'The Very Hungry Caterpillar', price_cents: 6133, listing_url: 'https://www.libris.ro/carte-engleza/the-very-hungry-caterpillar-eric-carle/15743846' },
      { title: 'Owl Babies', price_cents: 5178, listing_url: 'https://www.libris.ro/carte-engleza/owl-babies/10852618' },
    ],
  },
];

const CODE = encodeBuyList(buyListFromOrders(ORDERS));

function render(code = CODE, lang: 'en' | 'ro' = 'en'): ComponentFixture<BuyListComponent> {
  const fixture = TestBed.createComponent(BuyListComponent);
  fixture.componentRef.setInput('lang', lang);
  fixture.componentRef.setInput('code', code);
  fixture.detectChanges();
  return fixture;
}

function el(fixture: ComponentFixture<unknown>): HTMLElement {
  return fixture.nativeElement as HTMLElement;
}

describe('buy list per shop', () => {
  beforeEach(() => localStorage.clear());
  afterEach(() => localStorage.clear());

  it('renders one checklist per shop with price, listing link and a tick box', () => {
    const f = render();
    const sections = Array.from(el(f).querySelectorAll('section.shoplist'));
    expect(sections.map((s) => s.getAttribute('data-shop'))).toEqual(['amazon_de', 'libris']);
    expect(sections[0].querySelector('h2')!.textContent).toContain('Order at Amazon.de');
    expect(sections[1].querySelectorAll('.row').length).toBe(3);
    expect(sections[1].querySelectorAll('input.tick').length).toBe(3);
    expect(sections[1].textContent).toContain('61,33 lei');
    const links = Array.from(sections[0].querySelectorAll('a.listing')).map((a) => a.getAttribute('href'));
    expect(links).toEqual(['https://www.amazon.de/dp/1529105102', 'https://www.amazon.de/dp/0064431789']);
  });

  it('gives Libris its GET cart-add link in the spike form, and Amazon.de none', () => {
    const f = render();
    const [amazon, libris] = Array.from(el(f).querySelectorAll('section.shoplist'));
    expect(amazon.querySelector('a.cartadd')).toBeNull();
    expect(el(f).innerHTML).not.toContain('/gp/aws/cart/add');
    const carts = Array.from(libris.querySelectorAll('a.cartadd')).map((a) => a.getAttribute('href'));
    expect(carts).toEqual([
      'https://www.libris.ro/ajax/cart?addToCart=true&productId=21197307&quantity=1&strategy=once',
      'https://www.libris.ro/ajax/cart?addToCart=true&productId=15743846&quantity=1&strategy=once',
      'https://www.libris.ro/ajax/cart?addToCart=true&productId=10852618&quantity=1&strategy=once',
    ]);
    for (const shop of ['amazon_de', 'bookzone', 'emag', 'books_express']) {
      expect(librisCartUrl(shop, 'https://www.libris.ro/carte/x/123')).toBeNull();
    }
  });

  it('keeps ticks in localStorage under a key scoped to this list', () => {
    const f = render();
    const box = el(f).querySelectorAll<HTMLInputElement>('section.shoplist[data-shop="libris"] input.tick')[1];
    box.click();
    f.detectChanges();
    const saved = JSON.parse(localStorage.getItem(storageKey(CODE))!);
    expect(saved.ticks).toEqual(['libris/1']);

    const again = render();
    const boxes = el(again).querySelectorAll<HTMLInputElement>('section.shoplist[data-shop="libris"] input.tick');
    expect(Array.from(boxes).map((b) => b.checked)).toEqual([false, true, false]);

    const other = encodeBuyList(buyListFromOrders([ORDERS[1]]));
    expect(storageKey(other)).not.toBe(storageKey(CODE));
    const fresh = render(other);
    expect(Array.from(el(fresh).querySelectorAll<HTMLInputElement>('input.tick')).some((b) => b.checked)).toBeFalse();
  });

  it('round-trips the list through the share link code', () => {
    expect(CODE).toMatch(/^[A-Za-z0-9_-]+$/);
    expect(decodeBuyList(CODE)).toEqual(buyListFromOrders(ORDERS));
    const f = render();
    const share = el(f).querySelector<HTMLInputElement>('input.shareurl')!.value;
    expect(share.endsWith('#/buy/' + CODE)).toBeTrue();
    const code = share.split('#/buy/')[1];
    expect(decodeBuyList(code)![1].books[0].title).toBe('Ghici cât de mult te iubesc');
  });

  it('refuses a broken link and never shows an off-domain listing link', () => {
    expect(decodeBuyList('not*base64')).toBeNull();
    expect(decodeBuyList(btoa('{"x":1}'))).toBeNull();
    expect(el(render('garbage!')).textContent).toContain('This buy list link can’t be read.');
    const forged = encodeBuyList([{ store_id: 'libris', books: [{ title: 'X', price_cents: 100, listing_url: 'https://evil.example/carte/x/1' }] }]);
    const f = render(forged);
    expect(el(f).querySelector('a.listing')).toBeNull();
    expect(el(f).querySelector('a.cartadd')).toBeNull();
  });

  it('opens exactly one tab per tap and counts "n of total opened"', () => {
    const open = spyOn(window, 'open').and.returnValue(null);
    const f = render();
    const count = () => el(f).querySelector('.opened')!.textContent!.trim();
    expect(count()).toBe('0 of 5 opened');
    const button = () => el(f).querySelector<HTMLButtonElement>('button.opennext')!;
    expect(button().textContent).toContain('Open next: The Boy, the Mole, the Fox and the Horse at Amazon.de');
    button().click();
    f.detectChanges();
    expect(open).toHaveBeenCalledTimes(1);
    expect(open.calls.mostRecent().args[0]).toBe('https://www.amazon.de/dp/1529105102');
    button().click();
    button().click();
    f.detectChanges();
    expect(open).toHaveBeenCalledTimes(3);
    expect(count()).toBe('3 of 5 opened');
    expect(open.calls.allArgs().map((a) => a[0])).toEqual([
      'https://www.amazon.de/dp/1529105102',
      'https://www.amazon.de/dp/0064431789',
      'https://www.libris.ro/carte/ghici-cat-de-mult-te-iubesc-sam-mcbratney/21197307',
    ]);
    button().click();
    button().click();
    f.detectChanges();
    expect(open).toHaveBeenCalledTimes(5);
    expect(el(f).querySelector('button.opennext')).toBeNull();
    expect(el(f).textContent).toContain('All listings opened');
  });

  it('shows the stepper count and order heading in RO', () => {
    spyOn(window, 'open').and.returnValue(null);
    const f = render(CODE, 'ro');
    el(f).querySelector<HTMLButtonElement>('button.opennext')!.click();
    f.detectChanges();
    expect(el(f).querySelector('.opened')!.textContent!.trim()).toBe('1 din 5 deschise');
    expect(el(f).textContent).toContain('Comanda la Libris');
    expect(el(f).textContent).toContain('Adaugă în coșul Libris');
  });

  it('keeps all copy on comma-below ș/ț, says order/comandă, never the old word', () => {
    const all = Object.values(MESSAGES).flatMap((m) => Object.values(m)).join(' ');
    expect(/[\u015E\u015F\u0162\u0163]/.test(all)).toBeFalse();
    expect(new RegExp(['par', 'cel|colet'].join(''), 'i').test(all)).toBeFalse();
    expect(Object.keys(MESSAGES.ro).sort()).toEqual(Object.keys(MESSAGES.en).sort());
    expect(MESSAGES.ro.buyListLibrisCart).toContain('\u0219');
    expect(MESSAGES.en.buyListOrder).toContain('Order');
    expect(MESSAGES.ro.buyListOrder).toContain('Comanda');
  });
});

describe('buy list entry link on the result', () => {
  beforeEach(() => {
    const payload = {
      currency: 'RON',
      cached: true,
      read_at_range: { oldest: '2026-10-28', newest: '2026-10-28' },
      degraded: null,
      shops: [],
      books: [],
      failed_reads: [],
      cheapest: { status: 'ranked', reason: null, total_cents: 51516, books_subtotal_cents: 0, order_count: 2, orders: ORDERS.map((o) => ({ ...o, books: o.books.map((b) => ({ ...b, item_id: b.title })), delivery_gap: null, delivery_known: true, threshold_crossed: true })), delta_vs_cheapest_cents: 0, not_ranked: [] },
      one_order: { status: 'ranked', reason: null, best_store_id: null, answer: null, per_book_delta: [], shops: [] },
      custom: null,
      edition: { pins: {}, unknown_pins: [], status: 'ranked', reason: null, unpinned_total_cents: null, total_cents: null, delta_cents: null, not_ranked: [] },
    };
    spyOn(window, 'fetch').and.callFake(async () => new Response(JSON.stringify(payload), { status: 200 }));
  });

  it('links once to #/buy/<code> for the orders on screen', async () => {
    const fixture = TestBed.createComponent(AppComponent);
    demoSample();
    await fixture.componentInstance.load();
    fixture.componentInstance.route = { name: 'result', arg: '' };
    fixture.componentInstance.tab = 'cheapest';
    fixture.detectChanges();
    const links = Array.from(el(fixture).querySelectorAll<HTMLAnchorElement>('a[href^="#/buy/"]'));
    expect(links.length).toBe(1);
    expect(links[0].textContent!.trim()).toBe('Buy list for these orders');
    const code = links[0].getAttribute('href')!.slice('#/buy/'.length);
    expect(decodeBuyList(code)).toEqual(buyListFromOrders(ORDERS));
  });
});
