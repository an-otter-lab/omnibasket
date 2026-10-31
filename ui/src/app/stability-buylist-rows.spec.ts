import { ComponentFixture, TestBed } from '@angular/core/testing';
import { BuyListComponent } from './buy-list.component';
import { encodeBuyList } from './buy-list';

// S21: at phone width a Libris row (Open + Add to Libris cart) squeezed the title, dropped the
// price far below and let the buttons overlap it. One row per book: the tick and the title on
// the first line, the price and the buttons on the second.
const CODE = encodeBuyList([
  {
    store_id: 'libris',
    books: [
      { title: 'The Boy, the Mole, the Fox and the Horse', price_cents: 5660, listing_url: 'https://www.libris.ro/carte-engleza/the-boy-the-mole/1529105' },
      { title: 'Owl Babies', price_cents: 5178, listing_url: 'https://www.libris.ro/carte-engleza/owl-babies/10852618' },
    ],
  },
]);

function render(lang: 'en' | 'ro'): ComponentFixture<BuyListComponent> {
  const f = TestBed.createComponent(BuyListComponent);
  f.componentRef.setInput('lang', lang);
  f.componentRef.setInput('code', CODE);
  f.detectChanges();
  return f;
}

function overlap(a: DOMRect, b: DOMRect): boolean {
  return a.left < b.right - 0.5 && b.left < a.right - 0.5 && a.top < b.bottom - 0.5 && b.top < a.bottom - 0.5;
}

describe('S21 buy list rows', () => {
  beforeEach(() => localStorage.clear());
  afterEach(() => localStorage.clear());

  for (const lang of ['en', 'ro'] as const) {
    it(`keeps the price with the buttons, not in the title's line (${lang})`, () => {
      const f = render(lang);
      const rows = Array.from((f.nativeElement as HTMLElement).querySelectorAll('.row'));
      expect(rows.length).toBe(2);
      for (const row of rows) {
        const label = row.querySelector('label.rowlink')!;
        expect(label.querySelector('.price')).toBeNull();
        expect(label.querySelector('input.tick')).not.toBeNull();
        expect(label.querySelector('.bt')).not.toBeNull();
        const actions = row.querySelector('.rowr')!;
        expect(actions.firstElementChild!.classList).toContain('price');
        expect(actions.querySelector('a.listing')).not.toBeNull();
        expect(actions.querySelector('a.cartadd')).not.toBeNull();
      }
    });

    it(`never lets the price, the buttons and the title overlap (${lang})`, () => {
      const f = render(lang);
      document.body.appendChild(f.nativeElement);
      try {
        for (const row of Array.from((f.nativeElement as HTMLElement).querySelectorAll('.row'))) {
          const boxes = ['.bt', '.price', 'a.listing', 'a.cartadd'].map((s) => row.querySelector(s)!.getBoundingClientRect());
          for (let i = 0; i < boxes.length; i++) {
            for (let j = i + 1; j < boxes.length; j++) expect(overlap(boxes[i], boxes[j])).toBeFalse();
          }
          if (window.innerWidth < 768) {
            const [title, price, open] = boxes;
            expect(price.top).toBeGreaterThanOrEqual(title.bottom - 0.5); // second line
            expect(Math.abs(price.top + price.height / 2 - (open.top + open.height / 2))).toBeLessThan(2);
          }
        }
      } finally {
        f.nativeElement.remove();
      }
    });
  }
});
