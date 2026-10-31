import { TestBed } from '@angular/core/testing';
import { AppComponent } from './app.component';
import { MESSAGES } from './messages';
import { LANG_KEY } from './i18n';
import { PhotoReadResponse } from './photo';

// S19 (D2 pattern): while a photo is read, Photo of a list shows "Reading your list…", is disabled and
// takes no second photo (a second tap would be a second Muse call). It comes back when the read answers.

const NONE = { lines: [{ read_title: 'Nimic', read_author: null, status: 'not_found' }] } as PhotoReadResponse;

describe('S19 Photo of a list while the photo is read', () => {
  let answer: ((r: Response) => void) | null;
  let fail: ((e: unknown) => void) | null;
  let photoPosts: number;

  beforeEach(() => {
    answer = fail = null;
    photoPosts = 0;
    TestBed.configureTestingModule({});
    spyOn(window, 'fetch').and.callFake((input: RequestInfo | URL) => {
      if (String(input) !== '/photo') return Promise.resolve(new Response('{}', { status: 404 }));
      photoPosts++;
      return new Promise<Response>((resolve, reject) => {
        answer = resolve;
        fail = reject;
      });
    });
  });

  function boot(lang: 'en' | 'ro' = 'en') {
    if (lang === 'ro') localStorage.setItem(LANG_KEY, 'ro');
    const fixture = TestBed.createComponent(AppComponent);
    fixture.detectChanges();
    const el = fixture.nativeElement as HTMLElement;
    const button = () => el.querySelector<HTMLButtonElement>('#photo-trigger')!;
    const input = () => el.querySelector<HTMLInputElement>('input[type=file]')!;
    return { fixture, el, app: fixture.componentInstance, button, input };
  }

  function choose(app: AppComponent): Promise<void> {
    const file = new File([new Uint8Array([0xff, 0xd8, 0xff])], 'list.jpg', { type: 'image/jpeg' });
    const target = { files: [file], value: 'C:\\fakepath\\list.jpg' } as unknown as HTMLInputElement;
    return app.onEntryPhoto({ target } as unknown as Event);
  }

  const until = async (ok: () => boolean) => {
    for (let i = 0; i < 50 && !ok(); i++) await new Promise((r) => setTimeout(r, 0));
  };

  it('shows the loading state on the button and disables it until the read answers', async () => {
    const { fixture, app, button, input } = boot();
    expect(button().disabled).toBeFalse();
    expect(button().textContent!.trim()).toBe(MESSAGES.en.entryPhoto);

    const done = choose(app);
    await until(() => answer !== null);
    fixture.detectChanges();
    expect(button().disabled).toBeTrue();
    expect(button().getAttribute('aria-busy')).toBe('true');
    expect(button().textContent!.trim()).toBe('Reading your list…');
    expect(input().disabled).toBeTrue();

    answer!(new Response(JSON.stringify(NONE), { status: 200 }));
    await done;
    fixture.detectChanges();
    expect(app.photoState.kind).toBe('result');
    expect(app.photoReading).toBeFalse();
  });

  it('a second photo while the first is read sends no second request', async () => {
    const { app } = boot();
    const first = choose(app);
    await until(() => answer !== null);
    await choose(app);
    expect(photoPosts).toBe(1);
    answer!(new Response(JSON.stringify(NONE), { status: 200 }));
    await first;
    expect(photoPosts).toBe(1);
  });

  it('a failed read gives the button back with the failure note', async () => {
    const { fixture, el, app, button } = boot();
    const done = choose(app);
    await until(() => fail !== null);
    fail!(new TypeError('offline'));
    await done;
    fixture.detectChanges();
    expect(app.photoState.kind).toBe('failed');
    expect(button().disabled).toBeFalse();
    expect(button().textContent!.trim()).toBe(MESSAGES.en.entryPhoto);
    expect(el.textContent).toContain(MESSAGES.en.photoReadFail);
  });

  it('says it in Romanian too', async () => {
    const { fixture, app, button } = boot('ro');
    const done = choose(app);
    await until(() => answer !== null);
    fixture.detectChanges();
    expect(button().textContent!.trim()).toBe('Citesc lista…');
    expect(button().disabled).toBeTrue();
    answer!(new Response(JSON.stringify(NONE), { status: 200 }));
    await done;
  });
});
