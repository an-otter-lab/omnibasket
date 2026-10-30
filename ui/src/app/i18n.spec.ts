import { MESSAGES } from './messages';

describe('order / comandă copy', () => {
  const old = new RegExp(['par', 'cel|colet'].join(''), 'i');

  it('never uses the old word in either language', () => {
    for (const lang of ['en', 'ro'] as const) {
      expect(old.test(Object.values(MESSAGES[lang]).join(' '))).toBeFalse();
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
