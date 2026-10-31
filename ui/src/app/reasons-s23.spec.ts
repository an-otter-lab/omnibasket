import { TestBed } from '@angular/core/testing';
import { AppComponent } from './app.component';
import { LANG_KEY } from './i18n';
import { MESSAGES, reasonText } from './messages';

// S23: the result screen's "why not" lines came from the API in English ("no single shop lists every
// book" under "Niciun magazin nu le are pe toate"). The API now sends a code plus arguments, and the
// UI renders it from messages.ts.

const PLAN_CODES = [
  'no_shop_lists', 'no_chosen_shop_lists', 'no_shop_prints_as', 'no_chosen_shop_prints_as',
  'fee_not_printed_split', 'no_single_shop_fees', 'no_single_shop_lists_all', 'choose_a_shop',
  'chosen_shop_unusable', 'no_split_for_chosen', 'chosen_fees_not_printed', 'no_ranked_split', 'one_book', 'one_shop',
];
const SHOP_CODES = ['not_listed', 'out_of_stock', 'fees_not_printed', 'couldnt_read', 'other_edition'].map((c) => 'shop:' + c);
const LOCK_CODES = ['fees_not_printed', 'couldnt_read', 'not_listed', 'unknown_shop'].map((c) => 'lock:' + c);
const ARGS = { title: 'Simon vs. the Homo Sapiens Agenda', edition: 'hardcover', shops: ['emag', 'amazon_de'] };
const names: Record<string, string> = { emag: 'eMAG', amazon_de: 'Amazon.de' };
const shopName = (id: string) => names[id] ?? id;

describe('S23 reason lines in the shopper\'s language', () => {
  it('every code has an EN and a RO line, filled, with comma-below ș/ț', () => {
    for (const code of [...PLAN_CODES, ...SHOP_CODES, ...LOCK_CODES]) {
      const en = reasonText('en', code, ARGS, 'FALLBACK', shopName);
      const ro = reasonText('ro', code, ARGS, 'FALLBACK', shopName);
      expect(en).not.toBe('FALLBACK', code);
      expect(ro).not.toBe('FALLBACK', code);
      expect(ro).not.toBe(en, code);
      expect(en + ro).not.toMatch(/[{}]/);
      expect(ro).not.toMatch(/[şţŞŢ]/);
      expect(en + ro).not.toMatch(/parcel|colet/i);
    }
  });

  it('renders the two lines S23 saw in Romanian', () => {
    expect(reasonText('ro', 'no_single_shop_lists_all', {}, 'no single shop lists every book', shopName)).toBe(MESSAGES.ro.rsNoSingleShopListsAll);
    expect(reasonText('ro', 'no_chosen_shop_lists', { title: 'Simon vs. the Homo Sapiens Agenda' }, 'x', shopName))
      .toBe('niciunul dintre magazinele alese nu are Simon vs. the Homo Sapiens Agenda');
  });

  it('names shops and editions in the language', () => {
    expect(reasonText('en', 'chosen_shop_unusable', ARGS, '', shopName)).toBe('a chosen shop cannot be used: eMAG, Amazon.de');
    expect(reasonText('ro', 'no_shop_prints_as', ARGS, '', shopName)).not.toContain('hardcover');
  });

  it('an unknown or missing code shows the API\'s line instead of nothing', () => {
    expect(reasonText('ro', 'something_new', {}, 'english line', shopName)).toBe('english line');
    expect(reasonText('ro', null, undefined, 'english line', shopName)).toBe('english line');
    expect(reasonText('ro', null, undefined, null, shopName)).toBe('');
  });

  it('the component renders plan, shop-row and lock reasons in RO', () => {
    localStorage.setItem(LANG_KEY, 'ro');
    TestBed.configureTestingModule({});
    spyOn(window, 'fetch').and.returnValue(Promise.resolve(new Response('{}', { status: 404 })));
    const app = TestBed.createComponent(AppComponent).componentInstance;
    app.lang = 'ro';
    expect(app.why({ reason: 'no single shop lists every book', reason_code: 'no_single_shop_lists_all', reason_args: {} }))
      .toBe('niciun magazin nu are toate cărțile');
    expect(app.why({ reason: 'old english', reason_code: undefined })).toBe('old english');
    expect(app.why(null)).toBe('');
    expect(app.shopWhy('shop', 'out_of_stock', 'out of stock')).toBe('stoc epuizat');
    expect(app.shopWhy('lock', 'couldnt_read', 'its pages could not be read')).toBe('paginile nu au putut fi citite');
  });
});
