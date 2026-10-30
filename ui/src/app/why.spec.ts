import { ComponentFixture, TestBed } from '@angular/core/testing';
import { AppComponent } from './app.component';
import { MESSAGES } from './messages';

describe('split explanation', () => {
  let fixture: ComponentFixture<AppComponent>;
  let component: AppComponent;
  let fetchSpy: jasmine.Spy;

  beforeEach(async () => {
    fetchSpy = spyOn(globalThis, 'fetch').and.returnValue(Promise.resolve(({ ok: true, json: async () => ({}) } as Response)));
    await TestBed.configureTestingModule({ imports: [AppComponent] }).compileComponents();
    fixture = TestBed.createComponent(AppComponent);
    component = fixture.componentInstance;
  });

  function request(payload: object = {}) {
    return (component as unknown as { loadWhy: (p: unknown) => Promise<void> }).loadWhy(payload);
  }

  it('starts with the template and replaces it with a Muse paragraph and mark', async () => {
    fetchSpy.and.returnValue(Promise.resolve(({ ok: true, json: async () => ({ text: 'Muse paragraph.', source: 'muse' }) } as Response)));
    const pending = request({ items: [] });
    expect(component.whyText).toBe(MESSAGES.en.whySplitTemplate);
    await pending;
    expect(component.whyText).toBe('Muse paragraph.');
    expect(component.whyMuse).toBeTrue();
    expect(component.museLabel).toBe('Written by Muse');
  });

  it('keeps the template without a mark for template source', async () => {
    fetchSpy.and.returnValue(Promise.resolve(({ ok: true, json: async () => ({ text: 'fallback', source: 'template' }) } as Response)));
    await request();
    expect(component.whyText).toBe(MESSAGES.en.whySplitTemplate);
    expect(component.whyMuse).toBeFalse();
  });

  it('keeps the template on request failure without showing an error', async () => {
    fetchSpy.and.returnValue(Promise.reject(new Error('offline')));
    await request();
    expect(component.whyText).toBe(MESSAGES.en.whySplitTemplate);
    expect(component.whyMuse).toBeFalse();
    expect(component.note).toBe('');
  });

  it('uses localized EN and RO mark labels', () => {
    component.lang = 'en';
    expect(component.museLabel).toBe('Written by Muse');
    component.lang = 'ro';
    expect(component.museLabel).toBe('Scris de Muse');
  });

  it('ignores an older response after a newer request', async () => {
    let resolveOld!: (response: Response) => void;
    fetchSpy.and.returnValue(new Promise<Response>((resolve) => { resolveOld = resolve; }));
    const old = request();
    fetchSpy.and.returnValue(Promise.resolve(({ ok: true, json: async () => ({ text: 'new', source: 'muse' }) } as Response)));
    await request();
    resolveOld({ ok: true, json: async () => ({ text: 'old', source: 'muse' }) } as Response);
    await old;
    expect(component.whyText).toBe('new');
  });
});
