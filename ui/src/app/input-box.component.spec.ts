import { demoSample } from './demo-sample';
import { TestBed } from '@angular/core/testing';
import { AppComponent } from './app.component';
import { InputBoxComponent } from './input-box.component';

describe('the one-box first screen', () => {
  beforeEach(() => {
    window.location.hash = '';
  });

  it('shows one input with the exact prompt', () => {
    const fixture = TestBed.createComponent(InputBoxComponent);
    fixture.detectChanges();
    const el: HTMLElement = fixture.nativeElement;
    const inputs = el.querySelectorAll('input');
    expect(inputs.length).toBe(1);
    expect(inputs[0].getAttribute('placeholder')).toBe('Type a title, author or ISBN, or paste a link.');
    expect(inputs[0].getAttribute('aria-label')).toBe('Type a title, author or ISBN, or paste a link.');
  });

  it('makes the box the primary action and the photo button a secondary action', () => {
    window.location.hash = '#/';
    demoSample();
    const fixture = TestBed.createComponent(AppComponent);
    fixture.detectChanges();
    const el: HTMLElement = fixture.nativeElement;
    expect(el.querySelectorAll('input[type="search"]').length).toBe(1);
    // One primary button (find) and one secondary button (photo).
    expect(el.querySelectorAll('.btn').length).toBe(1);
    expect(el.querySelectorAll('.btn2').length).toBe(1);
    expect(el.querySelector('form .btn')).not.toBeNull();
    expect(el.querySelector('app-photo-input .btn2')).not.toBeNull();
    const sample = el.querySelector<HTMLAnchorElement>('a[data-sample]')!;
    expect(sample.textContent!.trim()).toBe('Try a sample basket');
    expect(sample.classList.contains('btn')).toBeFalse();
    expect(sample.getAttribute('href')).toContain('sample=ro-v1');
    const form = el.querySelector('form')!;
    // The sample link follows the form in document order.
    expect(form.compareDocumentPosition(sample) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it('emits the trimmed text on submit and nothing for an empty box', () => {
    const fixture = TestBed.createComponent(InputBoxComponent);
    const sent: string[] = [];
    fixture.componentInstance.submitted.subscribe((t) => sent.push(t));
    fixture.detectChanges();
    const el: HTMLElement = fixture.nativeElement;
    const input = el.querySelector('input')!;
    el.querySelector('form')!.dispatchEvent(new Event('submit'));
    expect(sent).toEqual([]);
    input.value = '  mackesy  ';
    input.dispatchEvent(new Event('input'));
    el.querySelector('form')!.dispatchEvent(new Event('submit'));
    expect(sent).toEqual(['mackesy']);
  });

  it('hides the sample link on the pick screen', () => {
    const fixture = TestBed.createComponent(InputBoxComponent);
    fixture.componentInstance.showSample = false;
    fixture.detectChanges();
    expect((fixture.nativeElement as HTMLElement).querySelector('a[data-sample]')).toBeNull();
  });
});
