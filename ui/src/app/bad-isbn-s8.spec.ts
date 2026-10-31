import { TestBed } from '@angular/core/testing';
import { AppComponent } from './app.component';
import { EVENT_SOURCE, SourceLike } from './events.service';
import { badIsbn } from './live';
import { MESSAGES } from './messages';

// S8: a mistyped ISBN is not a search. It says "This ISBN doesn't look right" and the field keeps the text.

class FakeSource implements SourceLike {
  onerror: ((e: unknown) => void) | null = null;
  constructor(readonly url: string) {}
  addEventListener(): void {}
  close(): void {}
}

describe('S8: a mistyped ISBN keeps its text and says why', () => {
  let searches: string[];

  beforeEach(() => {
    localStorage.clear();
    window.location.hash = '#/add';
    searches = [];
    TestBed.configureTestingModule({ providers: [{ provide: EVENT_SOURCE, useValue: (url: string) => new FakeSource(url) }] });
    spyOn(window, 'fetch').and.callFake(async (url: RequestInfo | URL) => {
      searches.push(String(url));
      return new Response(JSON.stringify({ results: [] }), { status: 200 });
    });
  });
  afterEach(() => {
    localStorage.clear();
    window.location.hash = '';
  });

  function boot() {
    const fixture = TestBed.createComponent(AppComponent);
    fixture.detectChanges();
    const el = fixture.nativeElement as HTMLElement;
    const input = el.querySelector<HTMLInputElement>('#entry-inp')!;
    const submit = (text: string) => {
      input.value = text;
      input.dispatchEvent(new Event('input'));
      el.querySelector<HTMLFormElement>('form.efield')!.dispatchEvent(new Event('submit', { cancelable: true }));
      fixture.detectChanges();
    };
    return { fixture, el, input, submit, app: fixture.componentInstance };
  }

  it('tells mistyped ISBNs from good ones and from titles', () => {
    expect(badIsbn('9780142402536')).toBeTrue(); // the walk's typo of 9780142402535
    expect(badIsbn('978-0-14-240253-6')).toBeTrue();
    expect(badIsbn('0306406153')).toBeTrue();
    expect(badIsbn('9780142402535')).toBeFalse();
    expect(badIsbn('0306406152')).toBeFalse();
    expect(badIsbn('Matilda')).toBeFalse();
    expect(badIsbn('12345')).toBeFalse();
    expect(badIsbn('1984')).toBeFalse();
  });

  it('a bad check digit: the message shows, the text stays, nothing is searched', () => {
    const { el, input, submit } = boot();
    submit('9780142402536');
    const note = el.querySelector('[data-state="isbn-wrong"]');
    expect(note).not.toBeNull();
    expect(note!.getAttribute('role')).toBe('alert');
    expect(note!.textContent).toContain('This ISBN doesn\u2019t look right');
    expect(input.value).toBe('9780142402536');
    expect(input.getAttribute('aria-invalid')).toBe('true');
    expect(searches.filter((u) => u.includes('/search'))).toEqual([]);
    expect(window.location.hash).toBe('#/add');
    expect(el.textContent).not.toContain(MESSAGES.en.pickEmpty);
  });

  it('typing again clears the message; a good ISBN then searches and empties the field (R0)', async () => {
    const { el, input, submit, fixture } = boot();
    submit('9780142402536');
    input.value = '9780142402535';
    input.dispatchEvent(new Event('input'));
    fixture.detectChanges();
    expect(el.querySelector('[data-state="isbn-wrong"]')).toBeNull();
    submit('9780142402535');
    expect(input.value).toBe('');
    expect(window.location.hash).toBe('#/find/9780142402535');
  });

  it('says it in Romanian too', () => {
    localStorage.setItem('omnibasket.lang.v1', 'ro');
    const { el, submit } = boot();
    submit('9780142402536');
    expect(el.querySelector('[data-state="isbn-wrong"]')!.textContent).toContain(MESSAGES.ro.isbnLooksWrong);
    expect(MESSAGES.ro.isbnLooksWrong).toContain('Verifică');
  });

  it('a #/find/ link with a mistyped ISBN puts it back in the field', async () => {
    window.location.hash = '#/find/9780142402536';
    const { el, input, fixture } = boot();
    await fixture.whenStable();
    fixture.detectChanges();
    expect(el.querySelector('[data-state="isbn-wrong"]')).not.toBeNull();
    expect(input.value).toBe('9780142402536');
    expect(searches.filter((u) => u.includes('/search'))).toEqual([]);
  });
});
