import { MESSAGES } from './messages';

describe('order / comandă copy', () => {
  const old = new RegExp(['par', 'cel|colet'].join(''), 'i');

  it('never uses the old word in either language (except entry screen v2)', () => {
    for (const lang of ['en', 'ro'] as const) {
      // Entry screen v2 explicitly uses "parcel"/"colet" in headline and step 3 per design spec
      const entryV2Keys = ['entryHeadline', 'entryStep3'];
      const otherMessages = Object.entries(MESSAGES[lang])
        .filter(([key]) => !entryV2Keys.includes(key))
        .map(([_, value]) => value)
        .join(' ');
      expect(old.test(otherMessages)).toBeFalse();
    }
  });

  it('reads 1 order / {n} orders in EN and 1 comandă / {n} comenzi in RO', () => {
    expect(MESSAGES.en.tabOne).toBe('1 order');
    expect(MESSAGES.en.tabMany).toBe('{n} orders');
    expect(MESSAGES.en.tabCheapest).toBe('cheapest');
    expect(MESSAGES.ro.tabOne).toBe('1 comandă');
    expect(MESSAGES.ro.tabMany).toBe('{n} comenzi');
  });

  it('has the same keys in both languages, with comma-below ș/ț', () => {
    expect(Object.keys(MESSAGES.ro).sort()).toEqual(Object.keys(MESSAGES.en).sort());
    expect(/[\u015E\u015F\u0162\u0163]/.test(Object.values(MESSAGES.ro).join(' '))).toBeFalse();
  });
});
