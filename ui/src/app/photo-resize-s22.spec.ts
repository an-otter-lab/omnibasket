import { TestBed } from '@angular/core/testing';
import { AppComponent } from './app.component';
import { PHOTO_LONG_SIDE, shrinkPhoto } from './photo';

// S22: a phone photo over 4 MB was refused. It is now drawn at most 2000 px on its long side and sent
// as a JPEG at 0.85, so a 6 MB, 4000 px camera JPEG is read and the request body is under 1 MB.

/** A camera-like JPEG: smooth gradients with grain, so it does not compress to nothing. */
async function cameraJpeg(w: number, h: number, quality = 0.95): Promise<Blob> {
  const c = document.createElement('canvas');
  c.width = w;
  c.height = h;
  const g = c.getContext('2d')!;
  const img = g.createImageData(w, h);
  const d = img.data;
  let s = 12345;
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      s = (s * 1103515245 + 12345) & 0x7fffffff;
      const n = (s >> 16) % 48;
      const i = (y * w + x) * 4;
      d[i] = ((x * 255) / w + n) | 0;
      d[i + 1] = ((y * 255) / h + n) | 0;
      d[i + 2] = (((x + y) % 256) + n) | 0;
      d[i + 3] = 255;
    }
  }
  g.putImageData(img, 0, 0);
  return new Promise<Blob>((done) => c.toBlob((b) => done(b!), 'image/jpeg', quality));
}

async function size(blob: Blob): Promise<[number, number]> {
  const bm = await createImageBitmap(blob);
  const wh: [number, number] = [bm.width, bm.height];
  bm.close();
  return wh;
}

describe('S22 phone photos are shrunk before upload', () => {
  let sent: { type: string; body: ArrayBuffer }[];

  beforeEach(() => {
    sent = [];
    TestBed.configureTestingModule({});
    spyOn(window, 'fetch').and.callFake((input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input) !== '/photo') return Promise.resolve(new Response('{}', { status: 404 }));
      const headers = (init?.headers ?? {}) as Record<string, string>;
      sent.push({ type: headers['content-type'], body: init!.body as ArrayBuffer });
      return Promise.resolve(new Response(JSON.stringify({ lines: [] }), { status: 200 }));
    });
  });

  function choose(app: AppComponent, blob: Blob, name: string): Promise<void> {
    const file = new File([blob], name, { type: blob.type });
    const target = { files: [file], value: 'C:\\fakepath\\' + name } as unknown as HTMLInputElement;
    return app.onEntryPhoto({ target } as unknown as Event);
  }

  function boot(): AppComponent {
    const fixture = TestBed.createComponent(AppComponent);
    fixture.detectChanges();
    return fixture.componentInstance;
  }

  it('reads a 6 MB, 4000 px camera JPEG with a request body under 1 MB', async () => {
    const photo = await cameraJpeg(4000, 3000);
    expect(photo.size).toBeGreaterThan(6 * 1000 * 1000);
    const app = boot();
    await choose(app, photo, 'IMG_0001.jpg');

    expect(app.photoState.kind).not.toBe('oversize');
    expect(sent.length).toBe(1);
    expect(sent[0].type).toBe('image/jpeg');
    expect(sent[0].body.byteLength).toBeLessThan(1000 * 1000);
    expect(await size(new Blob([sent[0].body], { type: 'image/jpeg' }))).toEqual([2000, 1500]);
  }, 20000);

  it('keeps a portrait photo upright and at most 2000 px on its long side', async () => {
    const out = await shrinkPhoto(await cameraJpeg(1500, 2600));
    expect(out.type).toBe('image/jpeg');
    const [w, h] = await size(out.body);
    expect(h).toBe(PHOTO_LONG_SIDE);
    expect(w).toBe(1154);
  });

  it('sends a small photo as it is', async () => {
    const c = document.createElement('canvas');
    c.width = 300;
    c.height = 200;
    c.getContext('2d')!.fillRect(0, 0, 100, 100);
    const png = await new Promise<Blob>((done) => c.toBlob((b) => done(b!), 'image/png'));
    const app = boot();
    await choose(app, png, 'list.png');

    expect(sent.length).toBe(1);
    expect(sent[0].type).toBe('image/png');
    expect(sent[0].body.byteLength).toBe(png.size);
  });

  it('still refuses a file over 4 MB the browser cannot read, with no /photo call', async () => {
    const junk = new Blob([new Uint8Array(5 * 1024 * 1024)], { type: 'image/jpeg' });
    const app = boot();
    await choose(app, junk, 'broken.jpg');

    expect(app.photoState.kind).toBe('oversize');
    expect(sent.length).toBe(0);
  });
});
