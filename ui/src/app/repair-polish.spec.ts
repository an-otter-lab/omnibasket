import { TestBed } from '@angular/core/testing';
import { AppComponent } from './app.component';
import { BasketService, normalisedKey } from './basket.service';
import { EVENT_SOURCE, SourceLike } from './events.service';
import { Candidate } from './live';
import { PickListComponent } from './pick-list.component';

// R12: a book already in the basket under another ISBN asks with "Add anyway" / "Keep one", it is
// never added silently. R15: the "Read prices ›" row is one native button the keyboard reaches.

const MATILDA_A: Candidate = { title: 'Matilda', author: 'Roald Dahl', isbn: '9780142410370', cover_url: null, shops: [] };
const MATILDA_B: Candidate = { title: 'MATILDA ', author: 'Dahl, Roald', isbn: '9786303684956', cover_url: null, shops: [] };
const OTHER: Candidate = { title: 'The BFG', author: 'Roald Dahl', isbn: '9780142410387', cover_url: null, shops: [] };

class FakeSource implements SourceLike {
  onerror: ((e: unknown) => void) | null = null;
  constructor(readonly url: string) {}
  addEventListener(): void {}
  close(): void {}
}

/** The ARIA role an element gets in the accessibility tree, by its tag (or an explicit role). */
function implicitRole(el: Element): string {
  const tag = el.tagName.toLowerCase();
  if (tag === 'button') return 'button';
  if (tag === 'a' && el.hasAttribute('href')) return 'link';
  return el.getAttribute('role') || 'generic';
}

/** The accessible name a screen reader would hear: the text left once hidden decoration is gone. */
function accessibleName(el: Element): string {
  const clone = el.cloneNode(true) as HTMLElement;
  clone.querySelectorAll('[aria-hidden="true"]').forEach((n) => n.remove());
  return (clone.textContent || '').replace(/\s+/g, ' ').trim();
}

function wait(): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, 0));
}

describe('the same book under another ISBN (R12)', () => {
  beforeEach(() => {
    localStorage.clear();
    window.location.hash = '';
    TestBed.configureTestingModule({ providers: [{ provide: EVENT_SOURCE, useValue: (url: string) => new FakeSource(url) }] });
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

  it('matches on the normalised title and author', () => {
    expect(normalisedKey('Micul Prinț!')).toBe(normalisedKey('micul  print'));
    expect(normalisedKey('Dahl, Roald')).toBe(normalisedKey('Roald Dahl'));
    expect(normalisedKey('MATILDA ')).toBe('matilda');
    expect(normalisedKey(null)).toBe('');
    expect(normalisedKey(undefined)).toBe('');
  });

  it('asks before the second copy joins, and adds nothing on its own', () => {
    const { fixture, el, app } = boot();
    app.pickBook(MATILDA_A);
    fixture.detectChanges();
    expect(el.querySelector('[data-state="add-duplicate"]')).toBeNull();

    app.pickBook(MATILDA_B);
    fixture.detectChanges();

    const ask = el.querySelector('[data-state="add-duplicate"]')!;
    expect(ask).not.toBeNull();
    // role=alert, never a silent block and never a quiet note.
    expect(ask.getAttribute('role')).toBe('alert');
    expect(ask.textContent).toContain('You already have this book (different edition). Add it anyway?');
    const add = ask.querySelector<HTMLButtonElement>('[data-action="duplicate-add"]')!;
    const keep = ask.querySelector<HTMLButtonElement>('[data-action="duplicate-keep"]')!;
    expect(add.tagName).toBe('BUTTON');
    expect(keep.tagName).toBe('BUTTON');
    expect(add.textContent).toContain('Add anyway');
    expect(keep.textContent).toContain('Keep one');
    // Nothing joined the basket while the question is open.
    expect(TestBed.inject(BasketService).items.length).toBe(1);
    expect(el.querySelectorAll('.addchip').length).toBe(1);
  });

  it('puts the focus on "Keep one" when the question opens', async () => {
    const { fixture, el, app } = boot();
    app.pickBook(MATILDA_A);
    fixture.detectChanges();
    app.pickBook(MATILDA_B);
    fixture.detectChanges();
    await wait();
    const keep = el.querySelector<HTMLButtonElement>('[data-action="duplicate-keep"]')!;
    expect(document.activeElement).toBe(keep);
  });

  it('"Keep one" adds nothing and keeps the copy already in the basket', () => {
    const { fixture, el, app } = boot();
    app.pickBook(MATILDA_A);
    fixture.detectChanges();
    app.pickBook(MATILDA_B);
    fixture.detectChanges();

    el.querySelector<HTMLButtonElement>('[data-action="duplicate-keep"]')!.click();
    fixture.detectChanges();

    expect(el.querySelector('[data-state="add-duplicate"]')).toBeNull();
    const items = TestBed.inject(BasketService).items;
    expect(items.length).toBe(1);
    expect(items[0].isbn).toBe('9780142410370');
    expect(app.route.name).toBe('add');
    expect(el.querySelectorAll('.addchip').length).toBe(1);
  });

  it('"Add anyway" keeps both copies and finishes the pick', () => {
    const { fixture, el, app } = boot();
    app.pickBook(MATILDA_A);
    fixture.detectChanges();
    app.pickBook(MATILDA_B);
    fixture.detectChanges();

    el.querySelector<HTMLButtonElement>('[data-action="duplicate-add"]')!.click();
    fixture.detectChanges();

    expect(el.querySelector('[data-state="add-duplicate"]')).toBeNull();
    const items = TestBed.inject(BasketService).items;
    expect(items.length).toBe(2);
    expect(items.map((i) => i.isbn).sort()).toEqual(['9780142410370', '9786303684956']);
    // The pick finished as a normal pick: the field is empty and the add state is showing.
    expect(app.route.name).toBe('add');
    expect(app.fieldText).toBe('');
    expect(el.querySelector('[data-live="added"]')!.textContent).toContain('Added');
  });

  it('a different book, or the same ISBN, never asks', () => {
    const { fixture, el, app } = boot();
    app.pickBook(MATILDA_A);
    fixture.detectChanges();
    app.pickBook(MATILDA_A);
    fixture.detectChanges();
    expect(el.querySelector('[data-state="add-duplicate"]')).toBeNull();
    expect(TestBed.inject(BasketService).items.length).toBe(1);

    app.pickBook(OTHER);
    fixture.detectChanges();
    expect(el.querySelector('[data-state="add-duplicate"]')).toBeNull();
    expect(TestBed.inject(BasketService).items.length).toBe(2);
  });

  it('says it in Romanian too, with the Romanian buttons', () => {
    const { fixture, el, app } = boot();
    app.lang = 'ro';
    fixture.detectChanges();
    app.pickBook(MATILDA_A);
    fixture.detectChanges();
    app.pickBook(MATILDA_B);
    fixture.detectChanges();

    const ask = el.querySelector('[data-state="add-duplicate"]')!;
    expect(ask.textContent).toContain('Ai deja cartea aceasta (altă ediție). O adaugi oricum?');
    expect(ask.querySelector('[data-action="duplicate-add"]')!.textContent).toContain('Adaugă oricum');
    expect(ask.querySelector('[data-action="duplicate-keep"]')!.textContent).toContain('Păstrează una');
  });
});

describe('the "Read prices" row is a real button (R15)', () => {
  function row(candidates: Candidate[]): { fixture: ReturnType<typeof TestBed.createComponent<PickListComponent>>; el: HTMLElement } {
    const fixture = TestBed.createComponent(PickListComponent);
    fixture.componentInstance.items = candidates;
    fixture.componentInstance.state = 'results';
    fixture.detectChanges();
    return { fixture, el: fixture.nativeElement as HTMLElement };
  }

  it('shows up as a button in the accessibility tree, named by the book and "Read prices"', () => {
    const { el } = row([MATILDA_A]);
    const button = el.querySelector<HTMLButtonElement>('[data-action="pick"]')!;
    expect(implicitRole(button)).toBe('button');
    expect(button.tagName).toBe('BUTTON');
    expect(button.type).toBe('button');
    expect(button.disabled).toBeFalse();
    const name = accessibleName(button);
    expect(name).toContain('Matilda');
    expect(name).toContain('Read prices');
    // The chevron is decoration, not part of the name.
    expect(name).not.toContain('›');
    expect(button.querySelector('.pchev')!.getAttribute('aria-hidden')).toBe('true');
  });

  it('is reachable by keyboard, and Enter/Space activate it because it is native', () => {
    const { fixture, el } = row([MATILDA_A]);
    const button = el.querySelector<HTMLButtonElement>('[data-action="pick"]')!;
    // A native button is in the tab order by itself: no tabindex is needed or set.
    expect(button.getAttribute('tabindex')).toBeNull();
    expect(button.tabIndex).toBe(0);
    button.focus();
    expect(document.activeElement).toBe(button);
    let picked: Candidate | null = null;
    fixture.componentInstance.picked.subscribe((c) => (picked = c));
    button.click();
    expect(picked).not.toBeNull();
    expect((picked as unknown as Candidate).isbn).toBe('9780142410370');
  });

  it('has no div or span carrying the pick action', () => {
    const { el } = row([MATILDA_A, OTHER]);
    const rows = Array.from(el.querySelectorAll<HTMLElement>('[data-action="pick"]'));
    expect(rows.length).toBe(2);
    for (const r of rows) expect(implicitRole(r)).toBe('button');
    expect(el.querySelectorAll('div[data-action="pick"], span[data-action="pick"]').length).toBe(0);
  });

  it('a row with no ISBN is a disabled button, not a hidden one', () => {
    const { el } = row([{ title: 'Unknown book', author: null, isbn: '', cover_url: null, shops: [] }]);
    const button = el.querySelector<HTMLButtonElement>('[data-action="pick"]')!;
    expect(implicitRole(button)).toBe('button');
    expect(button.disabled).toBeTrue();
    expect(button.textContent).not.toContain('Read prices');
  });
});
