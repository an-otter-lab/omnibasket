import { TestBed } from '@angular/core/testing';
import { AppComponent } from './app.component';

// S29: a new screen opens at its top (the result opened at "Your books", the buy list at its
// bottom); switching result tabs keeps the scroll position.

describe('S29 scroll to top on a route change', () => {
  let app: AppComponent;
  let scroll: jasmine.Spy;

  function goTo(hash: string): void {
    // replaceState sets the hash without a hashchange event; the handler is called once, by hand.
    window.history.replaceState(null, '', window.location.pathname + hash);
    app.onHash();
  }

  beforeEach(() => {
    spyOn(globalThis, 'fetch').and.resolveTo({ ok: true, json: async () => ({}) } as Response);
    app = TestBed.createComponent(AppComponent).componentInstance;
    app.loaded = true;
    goTo('#/result/cheapest');
    scroll = spyOn(window, 'scrollTo');
  });

  it('scrolls to the top when the result opens the buy list', () => {
    goTo('#/buy/abc');
    expect(scroll).toHaveBeenCalledOnceWith(0, 0);
  });

  it('scrolls to the top when the buy list goes back to the result', () => {
    goTo('#/buy/abc');
    scroll.calls.reset();
    goTo('#/result/cheapest');
    expect(scroll).toHaveBeenCalledOnceWith(0, 0);
  });

  it('keeps the position on a result tab switch', () => {
    goTo('#/result/one');
    goTo('#/result/custom');
    goTo('#/result/cheapest');
    expect(scroll).not.toHaveBeenCalled();
  });

  it('scrolls to the top between two orders, not on the same screen again', () => {
    goTo('#/order/libris');
    goTo('#/order/books-express');
    expect(scroll).toHaveBeenCalledTimes(2);
    scroll.calls.reset();
    goTo('#/order/books-express');
    expect(scroll).not.toHaveBeenCalled();
  });
});
