import { sameBook } from './basket.service';

// S25c (Adrian, 1 Nov): Find's "same book, other edition" match ignores a trailing ": subtitle",
// the same way it ignores a trailing "(…)".

const b = (isbn: string, title: string, author = 'Yuval Noah Harari') => ({ isbn, title, author });

describe('S25c sameBook ignores a trailing ": subtitle"', () => {
  it('"Sapiens: A Brief History of Humankind" is the same book as "Sapiens"', () => {
    expect(sameBook(b('9780099590088', 'Sapiens: A Brief History of Humankind'), b('9781846558238', 'Sapiens'))).toBeTrue();
    expect(sameBook(b('9781846558238', 'Sapiens'), b('9780099590088', 'Sapiens: A Brief History of Humankind'))).toBeTrue();
  });

  it('two different subtitles of one title, and a subtitle plus "(…)", match', () => {
    expect(sameBook(b('9780099590088', 'Sapiens: A Brief History of Humankind'), b('9786063333849', 'Sapiens: Scurtă istorie a omenirii'))).toBeTrue();
    expect(sameBook(b('9780099590088', 'Sapiens: A Brief History of Humankind (Vintage)'), b('9781846558238', 'Sapiens'))).toBeTrue();
  });

  it('still needs the same author and a different ISBN, and the title before the colon must match', () => {
    expect(sameBook(b('9780099590088', 'Sapiens: A Brief History'), b('9781846558238', 'Sapiens', 'Someone Else'))).toBeFalse();
    expect(sameBook(b('9780099590088', 'Sapiens: A Brief History'), b('9780099590088', 'Sapiens'))).toBeFalse();
    expect(sameBook(b('9780099590088', 'Homo Deus: A Brief History of Tomorrow'), b('9781846558238', 'Sapiens: A Brief History'))).toBeFalse();
  });

  it('a colon with no space after it is not a subtitle', () => {
    expect(sameBook(b('1', 'Ratio 3:2'), b('2', 'Ratio 3'))).toBeFalse();
  });
});
