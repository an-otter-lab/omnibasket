import { TestBed } from '@angular/core/testing';
import { AppComponent } from './app.component';

// S12: book prices read at different times on one day show that day, not "31–31 Oct".
describe('S12: the prices-read stamp', () => {
  afterEach(() => TestBed.createComponent(AppComponent).componentInstance.setLang('en'));

  function stamp(lang: 'en' | 'ro', oldest: string | null, newest: string | null): string {
    const app = TestBed.createComponent(AppComponent).componentInstance;
    app.setLang(lang);
    app.data = { read_at_range: { oldest, newest } } as unknown as AppComponent['data'];
    return app.stamp();
  }

  it('one day when every read is on the same day', () => {
    expect(stamp('en', '2026-10-31T09:12:00+02:00', '2026-10-31T23:05:00+02:00')).toBe('prices read 31 Oct');
    expect(stamp('ro', '2026-10-31T09:12:00+02:00', '2026-10-31T23:05:00+02:00')).toBe('prețuri citite 31 oct.');
  });

  it('a range across days is still a range', () => {
    expect(stamp('en', '2026-10-28T10:00:00+02:00', '2026-10-31T10:00:00+02:00')).toBe('prices read 28–31 Oct');
  });

  it('no reads, no stamp', () => {
    expect(stamp('en', null, null)).toBe('');
  });
});
