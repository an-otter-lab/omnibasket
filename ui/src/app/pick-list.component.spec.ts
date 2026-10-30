import { TestBed } from '@angular/core/testing';
import { Candidate } from './live';
import { PickListComponent } from './pick-list.component';

const BOOKS: Candidate[] = [
  {
    title: 'Harry Potter Hogwarts',
    author: null,
    isbn: '9781526605412',
    cover_url: 'https://covers.openlibrary.org/b/isbn/9781526605412-M.jpg',
    shops: [{ shop: 'books-express', url: 'https://www.books-express.ro/x/p/9781526605412' }],
  },
  {
    title: 'A shop image must never be a cover',
    author: 'Someone',
    isbn: '9780241564332',
    cover_url: 'https://s13emagst.akamaized.net/products/1/cover.jpg',
    shops: [{ shop: 'libris', url: 'https://www.libris.ro/x' }],
  },
  { title: 'No ISBN here', author: null, isbn: null, cover_url: null, shops: [] },
];

function render(items: Candidate[], state: 'results' | 'empty' | 'error' | 'searching' | 'link_failed' = 'results') {
  const fixture = TestBed.createComponent(PickListComponent);
  fixture.componentInstance.items = items;
  fixture.componentInstance.state = state;
  fixture.detectChanges();
  return fixture;
}

describe('the pick list', () => {
  it('renders covers from Open Library URLs and nothing else', () => {
    const el: HTMLElement = render(BOOKS).nativeElement;
    const imgs = Array.from(el.querySelectorAll('img'));
    expect(imgs.length).toBe(1);
    expect(imgs[0].getAttribute('src')).toBe('https://covers.openlibrary.org/b/isbn/9781526605412-M.jpg?default=false');
    for (const img of imgs) expect(img.src.startsWith('https://covers.openlibrary.org/')).toBeTrue();
    expect(el.innerHTML).not.toContain('akamaized');
    // The two books without an Open Library cover get the plain placeholder.
    expect(el.querySelectorAll('.pcover.ph').length).toBe(2);
  });

  it('lists the books with ISBN and where the index holds them', () => {
    const el: HTMLElement = render(BOOKS).nativeElement;
    const rows = el.querySelectorAll('li');
    expect(rows.length).toBe(3);
    expect(rows[0].textContent).toContain('Harry Potter Hogwarts');
    expect(rows[0].textContent).toContain('ISBN 9781526605412');
    expect(rows[0].textContent).toContain('Books-Express');
  });

  it('emits the picked book and disables one with no ISBN', () => {
    const fixture = render(BOOKS);
    const got: Candidate[] = [];
    fixture.componentInstance.picked.subscribe((c) => got.push(c));
    const buttons = (fixture.nativeElement as HTMLElement).querySelectorAll<HTMLButtonElement>('button.pick');
    buttons[0].click();
    expect(got.map((c) => c.isbn)).toEqual(['9781526605412']);
    expect(buttons[2].disabled).toBeTrue();
    expect(buttons[2].textContent).toContain('Paste the ISBN');
  });

  it('swaps a cover Open Library does not have for the placeholder', () => {
    const el: HTMLElement = render([BOOKS[0]]).nativeElement;
    el.querySelector('img')!.dispatchEvent(new Event('error'));
    expect(el.querySelector('img')).toBeNull();
    expect(el.querySelector('.pcover.ph')).not.toBeNull();
  });

  it('wraps a candidate line inside the card at 390px', () => {
    const fixture = render(BOOKS);
    const host: HTMLElement = fixture.nativeElement;
    const box = document.createElement('div');
    box.style.cssText = 'width:390px;padding:16px;overflow:hidden;box-sizing:border-box';
    document.body.appendChild(box);
    box.appendChild(host);
    const bad = host.querySelector<HTMLElement>('button.pick:disabled')!;
    expect(bad.scrollWidth).toBeLessThanOrEqual(bad.clientWidth + 1);
    for (const el of Array.from(host.querySelectorAll<HTMLElement>('.pmeta *'))) {
      expect(el.getBoundingClientRect().right).toBeLessThanOrEqual(bad.getBoundingClientRect().right + 1);
    }
    box.remove();
  });

  it('says so when nothing matches', () => {
    const el: HTMLElement = render([], 'empty').nativeElement;
    expect(el.textContent).toContain('Nothing in our index matches that');
  });
});
