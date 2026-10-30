import { MESSAGES } from './messages';
import { codeCopy, inlineTemplates, literalCopy, templateCopy } from './copy-scan';

// Feature 8: every user-facing string lives in messages.ts. This walks the app from
// app.component.ts through its imports, reads each source file as the test server
// serves it (/__src__/, a test-only asset in angular.json), and fails on copy written
// straight into a template or component code.

const ROOT = '/__src__/';
const KEYS = new Set(Object.keys(MESSAGES.en));

// Literals that look like copy but are not shown to anyone, with the reason.
const NOT_SHOWN: Record<string, string[]> = {
  // The stream's error text is not displayed: the app shows progFailed instead.
  'events.service.ts': ['The read failed.', 'The connection dropped.'],
};

async function read(path: string): Promise<string | null> {
  const res = await fetch(ROOT + path);
  return res.ok ? res.text() : null;
}

async function sources(): Promise<Map<string, string>> {
  const files = new Map<string, string>();
  const queue = ['app.component.ts'];
  while (queue.length) {
    const file = queue.shift()!;
    if (files.has(file)) continue;
    const text = await read(file);
    if (text == null) throw new Error('not served: ' + file);
    files.set(file, text);
    if (!file.endsWith('.ts')) continue;
    for (const m of text.matchAll(/from '\.\/([\w.-]+)'/g)) queue.push(m[1] + '.ts');
    for (const m of text.matchAll(/templateUrl:\s*'\.\/([\w.-]+)'/g)) queue.push(m[1]);
  }
  return files;
}

describe('hard-coded copy (feature 8)', () => {
  it('finds no copy outside messages.ts in the templates and components the app uses', async () => {
    const files = await sources();
    expect(files.size).toBeGreaterThan(10);
    const found: string[] = [];
    for (const [file, text] of files) {
      if (file === 'messages.ts') continue;
      const hits = file.endsWith('.html')
        ? templateCopy(text, KEYS)
        : [...inlineTemplates(text).flatMap((t) => templateCopy(t, KEYS)), ...codeCopy(text, KEYS)];
      for (const h of hits) if (!(NOT_SHOWN[file] || []).includes(h)) found.push(`${file}: ${h}`);
    }
    expect(found).toEqual([]);
  });

  it('catches the kinds of copy it is meant to catch', () => {
    expect(templateCopy('<p class="s">Delivery included</p>', KEYS)).toEqual(['Delivery included']);
    expect(templateCopy('<input placeholder="e.g. a title">', KEYS)).toEqual(['e.g. a title']);
    expect(templateCopy(`<a [attr.aria-label]="'Open ' + name">x</a>`, KEYS)).toContain('Open ');
    expect(templateCopy(`<span>{{ n === 1 ? 'book' : 'books' }}</span>`, KEYS)).toEqual(['book', 'books']);
    expect(templateCopy(`@if (x) { Off } @else { {{ m.off }} }`, KEYS)).toEqual(['Off']);
    expect(codeCopy(`const a = 'The solve failed.';`, KEYS)).toEqual(['The solve failed.']);
    expect(codeCopy('const t = `${n} book${n === 1 ? \'\' : \'s\'} from photo`;', KEYS).length).toBe(1);
  });

  it('lets through message keys, codes, routes, ISBN and syntax', () => {
    expect(templateCopy(`<a [href]="'#/book/' + id">{{ t('openOn', { shop: s }) }}</a>`, KEYS)).toEqual([]);
    expect(templateCopy(`@if (tab === 'one') { <p>ISBN {{ isbn }}</p> } @else if (x) { · }`, KEYS)).toEqual([]);
    expect(templateCopy(`<p>{{ count(n, 'book') }} · {{ m.edit }}</p>`, KEYS)).toEqual([]);
    expect(literalCopy(`status === 'not_ranked'`, KEYS)).toEqual([]);
  });
});
