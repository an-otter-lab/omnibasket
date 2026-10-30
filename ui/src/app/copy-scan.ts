// Feature 8: finds user-facing copy written straight into templates or component
// code instead of messages.ts. Used by copy-scan.spec.ts, which reads the sources
// the test server serves under /__src__/ (a test-only asset in angular.json).

export interface Finding {
  file: string;
  text: string;
}

const LETTER = /[A-Za-zĂÂÎȘȚăâîșț]/;
// Words that read the same in both languages and are not copy to translate.
const SAME_IN_BOTH = new Set(['ISBN']);
// Attributes whose static value is read out or shown.
const COPY_ATTRS = ['aria-label', 'aria-description', 'placeholder', 'title', 'alt', 'aria-placeholder', 'aria-roledescription'];
const CONTROL = /^@(else if|if|else|for|switch|case|default|empty|let|defer|placeholder|loading|error)\b/;

function skipParens(s: string, i: number): number {
  let depth = 0;
  for (; i < s.length; i++) {
    if (s[i] === '(') depth++;
    else if (s[i] === ')' && --depth === 0) return i + 1;
  }
  return i;
}

/** String literals inside a template expression that look like copy. */
export function literalCopy(expr: string, keys: Set<string>): string[] {
  const out: string[] = [];
  for (const m of expr.matchAll(/(['"])((?:\\.|(?!\1).)*)\1/g)) {
    const text = m[2];
    if (!LETTER.test(text) || keys.has(text) || SAME_IN_BOTH.has(text.trim())) continue;
    if (/^[#/?]/.test(text) || /^[\w.-]*\/[\w./-]*$/.test(text)) continue; // a route or a path
    const before = expr.slice(0, m.index).trimEnd();
    // A code compared against or passed to a function ('one_shop', 'book'), not shown as is.
    if (/^[a-z][a-z0-9_]*$/.test(text) && /(===|!==|==|!=|\(|,)$/.test(before)) continue;
    out.push(text);
  }
  return out;
}

/** Hard-coded copy in an Angular template. `keys` are the message keys (allowed as literals). */
export function templateCopy(template: string, keys: Set<string>): string[] {
  const out: string[] = [];
  let s = template.replace(/<!--[\s\S]*?-->/g, ' ');
  // Interpolations: check their literals, then drop them.
  s = s.replace(/\{\{([\s\S]*?)\}\}/g, (_, expr: string) => {
    out.push(...literalCopy(expr, keys));
    return ' ';
  });
  // Tags: static copy attributes and literals in bindings.
  s = s.replace(/<\/?[a-zA-Z][^>]*>/g, (tag) => {
    for (const m of tag.matchAll(/([\w.\-[\]()*@:]+)\s*=\s*"([^"]*)"/g)) {
      const [, name, value] = m;
      if (name.startsWith('(')) continue; // event handler: not shown
      if (name.startsWith('[') || name.startsWith('*')) out.push(...literalCopy(value, keys));
      else if (COPY_ATTRS.includes(name.toLowerCase()) && LETTER.test(value)) out.push(value);
    }
    return ' ';
  });
  // Control flow blocks (@if (...) {, } @else {, @let x = ...;) are syntax, not text.
  let text = '';
  for (let i = 0; i < s.length; ) {
    const m = s[i] === '@' ? CONTROL.exec(s.slice(i)) : null;
    if (m) {
      i += m[0].length;
      if (m[1] === 'let') {
        const end = s.indexOf(';', i);
        out.push(...literalCopy(s.slice(i, end), keys));
        i = end + 1;
        continue;
      }
      while (s[i] === ' ') i++;
      if (s[i] === '(') {
        const end = skipParens(s, i);
        out.push(...literalCopy(s.slice(i, end).replace(/^\(\s*'[^']*'\s*\)$/, ''), keys));
        i = end;
      }
      continue;
    }
    text += s[i] === '{' || s[i] === '}' ? ' ' : s[i];
    i++;
  }
  for (const chunk of text.split(/\s{2,}|\n/)) {
    const t = chunk.trim();
    if (t && LETTER.test(t) && !t.split(/\s+/).every((w) => !LETTER.test(w) || SAME_IN_BOTH.has(w))) out.push(t);
  }
  return out;
}

/** Inline templates in a component file. */
export function inlineTemplates(source: string): string[] {
  return [...source.matchAll(/template:\s*`([\s\S]*?)`/g)].map((m) => m[1]);
}

/**
 * String literals in component code that read as copy: two or more words with a
 * letter, or a capitalised word, outside imports, selectors, styles, errors and logs.
 */
export function codeCopy(source: string, keys: Set<string>): string[] {
  const code = source
    .replace(/template:\s*`[\s\S]*?`/g, '')
    .replace(/styles:\s*\[[\s\S]*?\]\s*,?\s*\n/g, '\n')
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/^\s*\/\/.*$/gm, '')
    .replace(/^\s*import[\s\S]*?;\s*$/gm, '')
    .replace(/(throw new Error|new Error|console\.\w+)\([^)]*\)/g, '');
  const out: string[] = [];
  for (const m of code.matchAll(/(['`])((?:\\.|(?!\1)[^\n])*)\1/g)) {
    const text = m[2];
    if (!LETTER.test(text) || keys.has(text)) continue;
    if (/^\(.*\)$/.test(text)) continue; // a media query
    // Class names, selectors and data attributes are not copy.
    if (/(className|classList\.\w+\(|querySelector(All)?\(|setAttribute\(|dataset\[?)\s*[=(]?\s*$/.test(code.slice(Math.max(0, m.index! - 40), m.index))) continue;
    const words = text.replace(/\$\{[^}]*\}/g, ' ').trim().split(/\s+/).filter((w) => LETTER.test(w));
    const prose = words.length >= 2 && words.every((w) => /^[A-Za-zĂÂÎȘȚăâîșț’'.,:;!?…()-]+$/.test(w));
    if (prose) out.push(text);
  }
  return out;
}
