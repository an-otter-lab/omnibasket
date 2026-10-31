import { TestBed } from '@angular/core/testing';
import { LiveProgressComponent } from './live-progress.component';
import { Progress } from './live';
import { Lang } from './messages';

// S9: progress lines come from store_id + status in the shopper's language, with honest marks.

describe('S9: live-progress lines and marks', () => {
  function render(lang: Lang, lines: Progress[]) {
    const fixture = TestBed.createComponent(LiveProgressComponent);
    fixture.componentInstance.lang = lang;
    fixture.componentInstance.lines = lines;
    fixture.detectChanges();
    const el = fixture.nativeElement as HTMLElement;
    return Array.from(el.querySelectorAll('.plog li')).map((li) => ({
      mark: li.querySelector('.dot')!.textContent!.trim(),
      text: li.querySelector('.pmsg')!.textContent!.trim(),
    }));
  }
  const p = (store_id: string, status: string, message = 'English server text: ' + status): Progress => ({ store_id, isbn13: '9780142402535', status, message });
  const ALL = [p('libris', 'ok'), p('bookzone', 'not_checked'), p('emag', 'not_checked'), p('books_express', 'cache'), p('carturesti', 'skipped'), p('emag', 'failed'), p('amazon_de', 'skipped')];

  it('EN: no raw status words, no server text, no tick for a shop that was not checked', () => {
    const got = render('en', ALL);
    expect(got.map((g) => g.text)).toEqual([
      'Libris: read', 'Bookzone: not checked', 'eMAG: couldn’t be read', 'Books-Express: read earlier today',
      'Cărturești: no match in our index', 'Amazon.de: not read live',
    ]);
    expect(got.map((g) => g.mark)).toEqual(['✓', '–', '✕', '✓', '–', '–']);
    for (const g of got) expect(g.text).not.toMatch(/not_checked|server text/);
  });

  it('RO: every line is Romanian', () => {
    const got = render('ro', [p('libris', 'reading'), ...ALL]);
    expect(got.map((g) => g.text)).toEqual([
      'Libris: citit', 'Bookzone: neverificat', 'eMAG: nu a putut fi citit', 'Books-Express: citit mai devreme azi',
      'Cărturești: nicio potrivire în indexul nostru', 'Amazon.de: nu se citește live',
    ]);
  });

  it('Amazon.de never gets a tick, even if the stream says ok', () => {
    const [a] = render('en', [p('amazon_de', 'ok')]);
    expect(a).toEqual({ mark: '–', text: 'Amazon.de: not read live' });
  });
});
