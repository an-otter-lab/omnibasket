import { TestBed } from '@angular/core/testing';
import { AskBoxComponent } from './ask-box.component';

// P3: "Ask" showed three times in a row (heading, field label, button). The field label stays
// for screen readers and is hidden on screen; the heading and the button stay visible.
describe('P3: the Ask field label', () => {
  for (const lang of ['en', 'ro'] as const) {
    it(`is visually hidden but still names the field (${lang})`, () => {
      const fixture = TestBed.createComponent(AskBoxComponent);
      fixture.componentInstance.lang = lang;
      fixture.componentInstance.data = { books: [], shops: [], cheapest: { status: 'ranked', orders: [], order_count: 0, total_cents: 0 }, custom: null, memberships: [], edition: { status: 'ranked', pins: {} } } as unknown as AskBoxComponent['data'];
      document.body.appendChild(fixture.nativeElement);
      fixture.detectChanges();
      const el = fixture.nativeElement as HTMLElement;
      const label = el.querySelector<HTMLLabelElement>('label.ask-label')!;
      const input = el.querySelector<HTMLInputElement>('#ask-inp')!;
      expect(label.htmlFor).toBe('ask-inp');
      expect(input.labels![0]).toBe(label);
      const box = label.getBoundingClientRect();
      expect(box.width).toBeLessThanOrEqual(1);
      expect(box.height).toBeLessThanOrEqual(1);
      expect(el.querySelector<HTMLElement>('.ask-title')!.getBoundingClientRect().height).toBeGreaterThan(1);
      expect(el.querySelector<HTMLElement>('.ask-go')!.getBoundingClientRect().height).toBeGreaterThan(1);
      fixture.nativeElement.remove();
    });
  }
});
