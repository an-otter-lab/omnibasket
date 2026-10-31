// P3: the total card fills the side column at 1440, and a wrapped buy-list label stays centred.
// The test browser is narrower than 1200 px, so this reads the global stylesheet's rules.

function rules(list: CSSRuleList, media: string | null): CSSStyleRule[] {
  const out: CSSStyleRule[] = [];
  for (const r of Array.from(list)) {
    if (r instanceof CSSMediaRule) {
      if (media && r.media.mediaText.replace(/\s/g, '') === media) out.push(...rules(r.cssRules, null));
    } else if (r instanceof CSSStyleRule && media === null) {
      out.push(r);
    }
  }
  return out;
}

function all(media: string | null): CSSStyleRule[] {
  const out: CSSStyleRule[] = [];
  for (const sheet of Array.from(document.styleSheets)) {
    try { out.push(...rules(sheet.cssRules, media)); } catch { /* cross-origin sheet */ }
  }
  return out;
}

describe('P3: result layout', () => {
  it('stretches the total card across the side column at 1200 px and up', () => {
    const wide = all('(min-width:1200px)').filter(r => r.selectorText === '.rtotal');
    expect(wide.length).toBeGreaterThan(0);
    const last = wide[wide.length - 1].style;
    expect(last.alignSelf).toBe('stretch');
    expect(last.justifySelf).toBe('stretch');
  });

  it('centres the buy-list button label when it wraps', () => {
    const cta = all(null).filter(r => r.selectorText === '.rcta' && r.style.textAlign);
    expect(cta.map(r => r.style.textAlign)).toContain('center');
  });
});
