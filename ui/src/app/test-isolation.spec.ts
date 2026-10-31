// Global isolation for every spec (jasmine hooks declared at file top level apply to all specs).
//
// Root cause of the 1-4 random failures out of 132 (a different set each run):
//  - Chrome throttles the History API (about 200 pushState/replaceState calls per 10 s per page) and then
//    silently ignores further calls. demo-sample.ts reset the URL with replaceState after EVERY spec (133),
//    plus demoSample() and the app's own leaveSample(). Near the limit, whether '?sample=ro-v1' actually
//    reached the URL depended on timing, so load() sometimes read sampleMode = false and rendered nothing:
//    delivery-gap, live-flow, memberships, book-read ... failed in a different order each run.
//  - On top of that, the specs shared one page: localStorage (basket, memberships, theme, lang), <html>
//    attributes, and the AppComponent constructor's fetch('/config') went to the real karma server and
//    resolved at an arbitrary time, so a finished spec's continuation (config, hashchange) hit the next spec.
//
//  - T1 (31 Oct 2026): skipping clean resets was not enough. Nearly every spec boots the app, which routes
//    through location.hash (1-4 navigations per spec), so one run of the whole suite still makes 200+
//    navigations inside one 10 s window. With random order, the specs past the limit kept the previous
//    spec's hash and their own route changes were dropped (add-book "#/find/Sapiens" -> '#/add', the buy
//    list entry link, "with 0 books"). ui/karma.conf.js now starts Chrome with the throttle off, and
//    resetUrl() below throws a named error if a reset is ever ignored again.
//
// What this file does, for every spec: a default offline fetch (no real network), a clean page before it, and
// a drain of pending continuations plus a clean page after it. The URL is touched ONLY when it is dirty,
// so the History API budget is never approached. Specs still install their own fetch stub with spyOn
// (allowRespy lets that replace the default); jasmine restores every spy after each spec.

jasmine.getEnv().allowRespy(true);

const realFetch = window.fetch.bind(window);

function resetUrl(): void {
  // replaceState clears search and hash without queueing a hashchange event; skip it when already clean.
  if (!(window.location.search || window.location.hash)) return;
  history.replaceState(null, '', window.location.pathname);
  // Chrome drops navigations silently once it throttles them (see ui/karma.conf.js). Fail here, by name,
  // instead of letting the next spec start on the previous spec's URL.
  if (window.location.search || window.location.hash) {
    throw new Error(
      `URL reset ignored (still ${window.location.search}${window.location.hash}): Chrome is throttling ` +
        'navigations. Run ng test with ui/karma.conf.js (--disable-ipc-flooding-protection).',
    );
  }
}

function resetBrowserState(): void {
  try {
    localStorage.clear();
    sessionStorage.clear();
  } catch {
    /* storage unavailable: nothing to reset */
  }
  resetUrl();
  const root = document.documentElement;
  delete root.dataset['theme'];
  delete root.dataset['themePref'];
  root.lang = 'en';
  const w = window as unknown as Record<string, unknown>;
  delete w['__np'];
  delete w['__unsel'];
}

const tick = () => new Promise<void>((resolve) => setTimeout(resolve, 0));

// Let promise chains and queued events (hashchange) of the spec that just ran settle while its own stubs are
// still installed, instead of leaking into the next spec.
async function drain(): Promise<void> {
  for (let i = 0; i < 3; i++) await tick();
}

beforeEach(async () => {
  resetBrowserState();
  // Default for specs that do not stub fetch: the API is not there (same outcome as the karma 404), but
  // immediately and with no network.
  spyOn(window, 'fetch').and.callFake(async (input: RequestInfo | URL) =>
    // /__src__/ is the test-only static asset copy-scan.spec reads; everything else is an unreachable API.
    String(input).startsWith('/__src__/') ? realFetch(input) : new Response('{}', { status: 404 }),
  );
  await drain();
});

afterEach(async () => {
  await drain();
  resetBrowserState();
});
