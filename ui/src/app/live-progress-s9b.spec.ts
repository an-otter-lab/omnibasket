import { TestBed } from '@angular/core/testing';
import { LiveProgressComponent } from './live-progress.component';
import { Progress } from './live';
import { Lang } from './messages';

// S9 follow-up (#28): a shop's result replaces its "Reading…" row and spinner; the status is said once.

describe('S9b: one row per shop, status said once', () => {
  function render(lang: Lang, lines: Progress[]): HTMLElement {
    const fixture = TestBed.createComponent(LiveProgressComponent);
    fixture.componentInstance.lang = lang;
    fixture.componentInstance.lines = lines;
    fixture.detectChanges();
    return fixture.nativeElement as HTMLElement;
  }
  const p = (store_id: string, status: string, isbn13 = '9780142402535'): Progress => ({ store_id, isbn13, status, message: '' });

  it('the result replaces the Reading row in place, with no spinner left', () => {
    const el = render('en', [p('libris', 'reading'), p('books_express', 'reading'), p('libris', 'ok')]);
    const rows = Array.from(el.querySelectorAll('.plog li'));
    expect(rows.map((r) => r.getAttribute('data-shop'))).toEqual(['libris', 'books_express']);
    expect(rows[0].getAttribute('data-status')).toBe('ok');
    expect(rows[0].querySelector('.dot.run')).toBeNull();
    expect(rows[0].textContent).not.toContain('Reading');
    expect(rows[1].querySelector('.dot.run')).not.toBeNull();
    expect(el.querySelectorAll('.dot.run').length).toBe(1);
  });

  it('the status word appears once per row (EN and RO)', () => {
    for (const lang of ['en', 'ro'] as Lang[]) {
      const el = render(lang, [p('libris', 'reading'), p('libris', 'ok'), p('emag', 'failed')]);
      const rows = Array.from(el.querySelectorAll('.plog li')).map((r) => r.textContent!.replace(/\s+/g, ' ').trim());
      const read = lang === 'en' ? /read/gi : /citit/gi;
      expect((rows[0].match(read) || []).length).toBe(1);
      expect(rows.length).toBe(2);
    }
  });

  it('the same shop for two books keeps two rows', () => {
    const el = render('en', [p('libris', 'ok', '9780142402535'), p('libris', 'ok', '9789734707751')]);
    expect(el.querySelectorAll('.plog li').length).toBe(2);
  });
});
