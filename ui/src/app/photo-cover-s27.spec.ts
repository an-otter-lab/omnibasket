import { TestBed } from '@angular/core/testing';
import { PhotoResultComponent } from './photo-result.component';
import { PhotoCandidate, PhotoState } from './photo';
import { coverFallback } from './live';

// S27: an Open Library cover that 404s (?default=false) or comes back as an empty 1-px image
// shows the initials placeholder, never the browser's broken-image icon or a blank box.
const CHARLOTTE: PhotoCandidate = {
  title: "Charlotte's Web",
  author: 'E. B. White',
  isbn: '9780064400558',
  cover_url: 'https://covers.openlibrary.org/b/isbn/9780064400558-M.jpg',
};
const HOBBIT: PhotoCandidate = { title: 'The Hobbit', author: 'J. R. R. Tolkien', isbn: '9780261103344', cover_url: 'https://covers.openlibrary.org/b/isbn/9780261103344-M.jpg' };

function render(state: PhotoState) {
  const fixture = TestBed.createComponent(PhotoResultComponent);
  fixture.componentInstance.lang = 'en';
  fixture.componentInstance.state = state;
  fixture.detectChanges();
  return fixture.nativeElement as HTMLElement;
}

const result = (matched: PhotoCandidate[], picks: PhotoCandidate[] = []): PhotoState => ({
  kind: 'result',
  matched: matched.map((c) => ({ read_title: c.title, read_author: c.author, candidate: c })),
  ambiguous: picks.length
    ? [{ line: { read_title: 'The Hobbit', read_author: null, status: 'ambiguous', candidates: picks }, picked: null }]
    : [],
  notFound: [],
});

describe('S27: broken cover images fall back to the initials placeholder', () => {
  it('a matched photo line whose cover 404s shows the initials, not a broken image', () => {
    const el = render(result([CHARLOTTE]));
    const img = el.querySelector('.photo-card img.pcover')!;
    expect(img).not.toBeNull();
    img.dispatchEvent(new Event('error'));
    expect(el.querySelector('.photo-card img')).toBeNull();
    expect(el.querySelector('.photo-card .pcover.ph')!.textContent!.trim()).toBe('CW');
  });

  it('a photo edition pick whose cover 404s shows the initials too', () => {
    const el = render(result([], [HOBBIT]));
    el.querySelector('.photo-ambiguous img.pcover')!.dispatchEvent(new Event('error'));
    expect(el.querySelector('.photo-ambiguous img')).toBeNull();
    expect(el.querySelector('.photo-ambiguous .pcover.ph')!.textContent!.trim()).toBe('TH');
  });

  it('an empty 1-px image is a missing cover; a real cover stays', () => {
    const host = document.createElement('div');
    const blank = document.createElement('img');
    blank.dataset['initials'] = 'CW';
    Object.defineProperty(blank, 'naturalWidth', { value: 1 });
    const real = document.createElement('img');
    Object.defineProperty(real, 'naturalWidth', { value: 180 });
    host.append(blank, real);
    // Called as the components' (load) handler would call it.
    coverFallback({ type: 'load', target: blank } as unknown as Event);
    coverFallback({ type: 'load', target: real } as unknown as Event);
    expect(host.querySelectorAll('img').length).toBe(1);
    expect(host.querySelector('.pcover.ph')!.textContent).toBe('CW');
  });

  it('a photo line with no cover at all shows the initials, not an empty box', () => {
    const el = render(result([{ ...CHARLOTTE, cover_url: null }]));
    expect(el.querySelector('.photo-card .pcover.ph')!.textContent!.trim()).toBe('CW');
  });
});
