import { TestBed } from '@angular/core/testing';
import { AppComponent } from './app.component';
import { BasketService } from './basket.service';
import { EVENT_SOURCE, SourceLike } from './events.service';
import { Candidate } from './live';

// R0 / R4: the add-book state. The field starts and stays empty (the query lives in #/find/<q>),
// a pick adds the book here without leaving the screen, and the first-run copy belongs to an
// empty basket at #/ only.

const A = '9781526605412';
const CAND: Candidate = {
  title: 'Harry Potter and the Philosopher’s Stone',
  author: 'J. K. Rowling',
  isbn: A,
  cover_url: null,
  shops: [],
};

class FakeSource implements SourceLike {
  handlers: Record<string, ((e: { data: string }) => void)[]> = {};
  onerror: ((e: unknown) => void) | null = null;
  constructor(readonly url: string) {}
  addEventListener(name: string, fn: (e: { data: string }) => void): void {
    (this.handlers[name] ||= []).push(fn);
  }
  close(): void {}
}

describe('the add-book state (R0, R4)', () => {
  let source: FakeSource | null;

  beforeEach(() => {
    source = null;
    localStorage.clear();
    window.location.hash = '';
    TestBed.configureTestingModule({ providers: [{ provide: EVENT_SOURCE, useValue: (url: string) => (source = new FakeSource(url)) }] });
  });

  afterEach(() => {
    localStorage.clear();
    window.location.hash = '';
  });

  function boot(): { fixture: ReturnType<typeof TestBed.createComponent<AppComponent>>; el: HTMLElement; app: AppComponent } {
    const fixture = TestBed.createComponent(AppComponent);
    fixture.detectChanges();
    return { fixture, el: fixture.nativeElement as HTMLElement, app: fixture.componentInstance };
  }

  function type(el: HTMLElement, text: string): HTMLInputElement {
    const input = el.querySelector<HTMLInputElement>('#entry-inp')!;
    input.value = text;
    input.dispatchEvent(new Event('input'));
    return input;
  }

  it('empties the field after a pick, clears the rows and says what was added', () => {
    const { fixture, el, app } = boot();
    app.route = { name: 'find', arg: 'Sapiens' };
    app.candidates = [CAND];
    app.pickState = 'results';
    fixture.detectChanges();

    const input = type(el, 'Harry Potter');
    fixture.detectChanges();
    expect(input.value).toBe('Harry Potter');

    app.pickBook(CAND);
    fixture.detectChanges();

    // R0: the field is '' once a book is picked, and the list is gone.
    expect(app.fieldText).toBe('');
    expect(el.querySelector<HTMLInputElement>('#entry-inp')!.value).toBe('');
    expect(el.querySelectorAll('button.pick').length).toBe(0);

    // R4: the pick added the book here; no navigation to the read screen.
    expect(app.route.name).toBe('add');
    expect(el.querySelector('[data-live="added"]')!.textContent).toContain('Added Harry Potter and the Philosopher’s Stone.');
    expect(el.querySelector('[data-live="added"]')!.textContent).toContain('1 book in your basket');
    expect(el.querySelector('[data-header-count]')!.textContent).toContain('1 book');
    expect(el.querySelectorAll('.addchip').length).toBe(1);
    expect(el.querySelector('[data-action="see-orders"]')).not.toBeNull();

    // The prices are read for the picked ISBN, in the background.
    expect(source!.url).toContain('source=live');
    expect(source!.url).toContain('isbn13=' + A);
  });

  it('a read that fails leaves no phantom book and says so', () => {
    const { fixture, el, app } = boot();
    app.route = { name: 'find', arg: 'Sapiens' };
    app.pickState = 'results';
    app.candidates = [CAND];
    fixture.detectChanges();
    app.pickBook(CAND);
    fixture.detectChanges();
    expect(TestBed.inject(BasketService).items.length).toBe(1);

    source!.onerror!({});
    fixture.detectChanges();

    expect(TestBed.inject(BasketService).items.length).toBe(0);
    expect(el.querySelector('[data-state="add-read-failed"]')!.textContent).toContain('Couldn’t read prices for Harry Potter and the Philosopher’s Stone.');
    expect(el.querySelectorAll('.addchip').length).toBe(0);
  });

  it('"Add a book" with a non-empty basket shows the add state, never the first-run headline', () => {
    TestBed.inject(BasketService).addUnpriced(A, 'Book A', 'Author A');
    const { el } = boot();

    expect(el.querySelector('[data-screen="first"]')).toBeNull();
    expect(el.querySelector('[data-screen="add"]')).not.toBeNull();
    expect(el.textContent).not.toContain('One order, or the cheapest?');
    expect(el.textContent).not.toContain('How it works');
    expect(el.textContent).toContain('Find a book');
    expect(el.querySelector('[data-header-count]')!.textContent).toContain('1 book · See orders');
    expect(el.querySelectorAll('.addchip').length).toBe(1);
    expect(el.querySelector('.addtitle')!.textContent).toContain('Book A · Author A');
  });

  it('keeps the first-run copy for an empty basket at #/', () => {
    const { el } = boot();
    expect(el.querySelector('[data-screen="first"]')).not.toBeNull();
    expect(el.textContent).toContain('One order, or the cheapest?');
    expect(el.textContent).toContain('How it works');
    expect(el.querySelector('[data-header-count]')).toBeNull();
    expect(el.querySelectorAll('.addchip').length).toBe(0);
  });

  it('routes #/add to the add state with the field already empty', () => {
    window.location.hash = '#/add';
    const { el, app } = boot();
    expect(app.route.name).toBe('add');
    expect(el.querySelector('[data-screen="add"]')).not.toBeNull();
    expect(el.querySelector<HTMLInputElement>('#entry-inp')!.value).toBe('');
  });

  it('empties the field as soon as a typed query is submitted, and keeps it in the URL', () => {
    const { fixture, el, app } = boot();
    const input = type(el, 'Sapiens');
    fixture.detectChanges();
    expect(input.value).toBe('Sapiens');

    el.querySelector('form')!.dispatchEvent(new Event('submit'));
    fixture.detectChanges();

    expect(app.fieldText).toBe('');
    expect(el.querySelector<HTMLInputElement>('#entry-inp')!.value).toBe('');
    expect(window.location.hash).toBe('#/find/Sapiens');
  });

  it('the no-match line carries a Clear button back to the empty field', () => {
    const { fixture, el, app } = boot();
    app.route = { name: 'find', arg: 'zzzz' };
    app.pickState = 'empty';
    fixture.detectChanges();
    const input = type(el, 'zzzz');
    fixture.detectChanges();
    expect(input.value).toBe('zzzz');
    expect(el.textContent).toContain('No match');

    el.querySelector<HTMLButtonElement>('[data-action="clear"]')!.click();
    fixture.detectChanges();

    expect(app.pickState).toBe('idle');
    expect(app.fieldText).toBe('');
    expect(el.querySelector<HTMLInputElement>('#entry-inp')!.value).toBe('');
  });
});
