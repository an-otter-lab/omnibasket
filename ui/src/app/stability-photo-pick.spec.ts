import { ComponentFixture, TestBed, fakeAsync, tick } from '@angular/core/testing';
import { HttpClientTestingModule } from '@angular/common/http/testing';
import { Subject } from 'rxjs';
import { AppComponent } from './app.component';
import { PhotoReadResponse } from './photo';
import { EventsService, LiveEvent } from './events.service';

/** S15: a pick on the photo result lands on its own line, whatever the candidate's position. */
describe('S15 photo picks land on their own line', () => {
  let component: AppComponent;
  let fixture: ComponentFixture<AppComponent>;
  let eventsService: jasmine.SpyObj<EventsService>;

  const BOY = '9781529105100';
  const MATILDA_COLOUR = '9780241558317';
  const MATILDA = '9780142410370';
  const response: PhotoReadResponse = {
    lines: [
      {
        read_title: 'The Boy, the Mole, the Fox and the Horse', read_author: 'Charlie Mackesy', status: 'ambiguous',
        candidates: [{ title: 'The Boy, the Mole, the Fox and the Horse', author: 'Charlie Mackesy', isbn: BOY, cover_url: null }],
      },
      {
        read_title: 'Matilda', read_author: 'Roald Dahl', status: 'ambiguous',
        candidates: [
          { title: 'Matilda (Colour Edition)', author: 'Roald Dahl', isbn: MATILDA_COLOUR, cover_url: null },
          { title: 'Matilda', author: 'Roald Dahl', isbn: MATILDA, cover_url: null },
        ],
      },
    ],
  };

  beforeEach(async () => {
    localStorage.clear();
    window.location.hash = '';
    eventsService = jasmine.createSpyObj('EventsService', ['open']);
    await TestBed.configureTestingModule({
      imports: [HttpClientTestingModule, AppComponent],
      providers: [{ provide: EventsService, useValue: eventsService }],
    }).compileComponents();
    fixture = TestBed.createComponent(AppComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  afterEach(() => {
    window.location.hash = '';
    localStorage.clear();
  });

  function lines(): HTMLElement[] {
    return Array.from((fixture.nativeElement as HTMLElement).querySelectorAll<HTMLElement>('.photo-ambiguous'));
  }

  it('clicking a pick on each of two lines resolves each line to its own book, and both are read', fakeAsync(() => {
    component.onPhotoEvent({ kind: 'read', response });
    component.route = { name: 'photo', arg: '' };
    tick();
    fixture.detectChanges();
    expect(lines().length).toBe(2);

    // Line 1's book is its only (first) candidate; line 2's is its second candidate.
    lines()[0].querySelectorAll<HTMLButtonElement>('button.pick')[0].click();
    fixture.detectChanges();
    lines()[1].querySelectorAll<HTMLButtonElement>('button.pick')[1].click();
    fixture.detectChanges();
    if (component.photoState.kind !== 'result') fail('photo result expected');
    else {
      expect(component.photoState.ambiguous.map((a) => a.picked?.isbn)).toEqual([BOY, MATILDA]);
    }
    expect(lines()[0].querySelector('button.pick.sel')!.textContent).toContain(BOY);
    expect(lines()[1].querySelector('button.pick.sel')!.textContent).toContain(MATILDA);

    eventsService.open.and.callFake(() => new Subject<LiveEvent>().asObservable());
    component.onPhotoContinue();
    tick();
    const urls = eventsService.open.calls.allArgs().map((a) => String(a[0]));
    expect(urls.length).toBe(2);
    expect(urls.some((u) => u.includes(BOY))).toBeTrue();
    expect(urls.some((u) => u.includes(MATILDA) && !u.includes(MATILDA_COLOUR))).toBeTrue();
    expect(urls.some((u) => u.includes(MATILDA_COLOUR))).toBeFalse();
  }));

  it('a first-candidate pick on the second line does not overwrite the first line', fakeAsync(() => {
    component.onPhotoEvent({ kind: 'read', response });
    component.route = { name: 'photo', arg: '' };
    tick();
    fixture.detectChanges();
    lines()[0].querySelectorAll<HTMLButtonElement>('button.pick')[0].click();
    lines()[1].querySelectorAll<HTMLButtonElement>('button.pick')[0].click();
    fixture.detectChanges();
    if (component.photoState.kind !== 'result') fail('photo result expected');
    else expect(component.photoState.ambiguous.map((a) => a.picked?.isbn)).toEqual([BOY, MATILDA_COLOUR]);
  }));
});
