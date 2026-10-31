import { TestBed } from '@angular/core/testing';
import { AppComponent } from './app.component';
import { BasketItem, BasketService, sameBook } from './basket.service';
import { EVENT_SOURCE, SourceLike } from './events.service';
import { PhotoState, ResolvedLine } from './photo';

// S26: the photo path asks the R12 question too. A photo line that is a book already in the basket
// (or an earlier line of the same photo) under another ISBN is asked about, one at a time, and no
// live read starts before every question is answered.

const MATILDA = '9780142410370';
const MATILDA_COLOUR = '9780241558317';
const BFG = '9780142410387';

const opened: string[] = [];
class FakeSource implements SourceLike {
  onerror: ((e: unknown) => void) | null = null;
  constructor(readonly url: string) { opened.push(url); }
  addEventListener(): void {}
  close(): void {}
}

function line(title: string, isbn: string, author = 'Roald Dahl'): ResolvedLine {
  return { read_title: title, read_author: author, candidate: { title, author, isbn, cover_url: null } };
}

function item(title: string, isbn: string): BasketItem {
  return { id: 'book-' + isbn, isbn, title, author: 'Roald Dahl', offers: [], live_offers: [] };
}

function settle(): Promise<void> {
  return new Promise((r) => setTimeout(r, 0));
}

describe('S26: the photo path asks before a second copy joins (R12)', () => {
  beforeEach(() => {
    localStorage.clear();
    opened.length = 0;
    window.location.hash = '';
    TestBed.configureTestingModule({ providers: [{ provide: EVENT_SOURCE, useValue: (url: string) => new FakeSource(url) }] });
  });
  afterEach(() => {
    TestBed.inject(BasketService).items = [];
    localStorage.clear();
    window.location.hash = '';
  });

  async function photo(matched: ResolvedLine[]) {
    const fixture = TestBed.createComponent(AppComponent);
    fixture.detectChanges();
    await settle();
    const app = fixture.componentInstance;
    app.photoState = { kind: 'result', matched, ambiguous: [], notFound: [] } as PhotoState;
    app.route = { name: 'photo', arg: '' };
    fixture.detectChanges();
    return { fixture, app, el: fixture.nativeElement as HTMLElement };
  }

  const reads = () => opened.map((u) => [MATILDA, MATILDA_COLOUR, BFG].find((i) => u.includes(i)));

  it('a trailing "(…)" edition note is the same book; another author or the same ISBN is not', () => {
    const a = { isbn: MATILDA, title: 'Matilda', author: 'Roald Dahl' };
    expect(sameBook(a, { isbn: MATILDA_COLOUR, title: 'Matilda (Colour Edition)', author: 'Dahl, Roald' })).toBeTrue();
    expect(sameBook(a, { isbn: MATILDA, title: 'Matilda (Colour Edition)', author: 'Roald Dahl' })).toBeFalse();
    expect(sameBook(a, { isbn: MATILDA_COLOUR, title: 'Matilda (Colour Edition)', author: 'Someone Else' })).toBeFalse();
    expect(sameBook(a, { isbn: BFG, title: 'The BFG', author: 'Roald Dahl' })).toBeFalse();
  });

  it('Matilda in the basket, Matilda (Colour Edition) on the photo: asks, reads nothing, "Keep one" reads only the other book', async () => {
    TestBed.inject(BasketService).items = [item('Matilda', MATILDA)];
    const { fixture, app, el } = await photo([line('Matilda (Colour Edition)', MATILDA_COLOUR), line('The BFG', BFG)]);
    app.onPhotoContinue();
    fixture.detectChanges();
    const ask = el.querySelector('[data-state="photo-duplicate"]')!;
    expect(ask).not.toBeNull();
    expect(ask.getAttribute('role')).toBe('alert');
    expect(ask.textContent).toContain('Matilda (Colour Edition)');
    expect(ask.textContent).toContain('You already have this book (different edition). Add it anyway?');
    expect(opened.length).toBe(0);
    app.onPhotoContinue(); // a second Continue while asking does nothing
    expect(opened.length).toBe(0);

    ask.querySelector<HTMLButtonElement>('[data-action="duplicate-keep"]')!.click();
    fixture.detectChanges();
    expect(el.querySelector('[data-state="photo-duplicate"]')).toBeNull();
    expect(reads()).toEqual([BFG]);
  });

  it('"Add anyway" reads both lines', async () => {
    TestBed.inject(BasketService).items = [item('Matilda', MATILDA)];
    const { fixture, app, el } = await photo([line('Matilda (Colour Edition)', MATILDA_COLOUR), line('The BFG', BFG)]);
    app.onPhotoContinue();
    fixture.detectChanges();
    el.querySelector<HTMLButtonElement>('[data-state="photo-duplicate"] [data-action="duplicate-add"]')!.click();
    fixture.detectChanges();
    expect(reads().sort()).toEqual([MATILDA_COLOUR, BFG].sort());
  });

  it('two lines of the same photo that are the same book: asks on the second', async () => {
    const { fixture, app, el } = await photo([line('Matilda', MATILDA), line('Matilda (Colour Edition)', MATILDA_COLOUR)]);
    app.onPhotoContinue();
    fixture.detectChanges();
    expect(el.querySelector('[data-state="photo-duplicate"]')?.textContent).toContain('Matilda (Colour Edition)');
    expect(opened.length).toBe(0);
    el.querySelector<HTMLButtonElement>('[data-state="photo-duplicate"] [data-action="duplicate-keep"]')!.click();
    expect(reads()).toEqual([MATILDA]);
  });

  it('no duplicate: reads every line at once, no question', async () => {
    const { fixture, app, el } = await photo([line('Matilda', MATILDA), line('The BFG', BFG)]);
    app.onPhotoContinue();
    fixture.detectChanges();
    expect(el.querySelector('[data-state="photo-duplicate"]')).toBeNull();
    expect(reads().sort()).toEqual([MATILDA, BFG].sort());
  });
});
