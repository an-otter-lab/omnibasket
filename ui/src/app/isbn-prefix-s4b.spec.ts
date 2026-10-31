import { badIsbn, parseInput, toIsbn13 } from './live';

// S4b: a 13-digit number that does not start 978 or 979 is never an ISBN-13.

describe('S4b: only 978/979 numbers are ISBN-13s in the app', () => {
  it('toIsbn13 turns away barcodes whose check digit works out', () => {
    expect(toIsbn13('6421234567895')).toBeNull();
    expect(toIsbn13('5012345678900')).toBeNull();
    expect(toIsbn13('9780142402535')).toBe('9780142402535');
    expect(toIsbn13('979-10-90636-07-1')).toBe('9791090636071');
    expect(toIsbn13('0306406152')).toBe('9780306406157');
  });

  it('a typed barcode is not an ISBN search and gets the S8 note', () => {
    expect(parseInput('6421234567895').kind).not.toBe('isbn');
    expect(badIsbn('6421234567895')).toBeTrue();
    expect(badIsbn('9780142402535')).toBeFalse();
  });
});
