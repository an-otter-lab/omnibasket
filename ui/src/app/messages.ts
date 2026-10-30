// RO and EN copy. Feature 8 moves the rest of the app's copy here and adds the
// browser-language default and the toggle. Until then the app runs in 'en'.
// Rules: "order" in EN, "comandă" in RO, never "parcel"/"colet".
// Romanian uses comma-below ș/ț (U+0219/U+021B), never the cedilla forms (U+015F/U+0163).

export type Lang = 'en' | 'ro';

export interface Messages {
  /** {amount} is already formatted as the app formats lei (e.g. 153,50). */
  deliveryGapShort: string;
  deliveryGapReached: string;

  // Feature 6: buy list per shop.
  buyListEntry: string;
  buyListTitle: string;
  buyListIntro: string;
  /** {shop} */
  buyListOrder: string;
  buyListOpen: string;
  /** {title} {shop} */
  buyListOpenLabel: string;
  buyListNoLink: string;
  /** {title} */
  buyListTickLabel: string;
  buyListLibrisCart: string;
  /** {title} */
  buyListLibrisCartLabel: string;
  buyListLibrisCartNote: string;
  /** {title} {shop} */
  buyListOpenNext: string;
  /** {opened} {total} */
  buyListOpenedCount: string;
  buyListAllOpened: string;
  buyListStartAgain: string;
  buyListStepperNote: string;
  buyListShare: string;
  buyListShareHint: string;
  buyListShareLabel: string;
  buyListCopied: string;
  buyListInvalid: string;
  buyListBack: string;

  // Feature 5: declared memberships. {name} is the membership, {shop} the shop.
  membershipsTitle: string;
  membershipsIntro: string;
  /** {name} */
  membershipDeclare: string;
  /** {name} {rule} {threshold}: rule is the shop's printed amount (e.g. 49 €), threshold the lei the solver uses. */
  membershipNone: string;
  /** {name} */
  membershipNoneNoRule: string;
  /** {name} {shop} */
  membershipUnknown: string;
  /** {name} {shop} {threshold} */
  membershipThreshold: string;
  membershipTotalsSame: string;
  /** {url} {date} */
  membershipSourceRead: string;
  /** {url} {date} */
  membershipSourceTried: string;
  /** Twelve short month names, space-separated. */
  monthsShort: string;
}

export const MESSAGES: Record<Lang, Messages> = {
  en: {
    deliveryGapShort: '{amount} lei short of free delivery at {shop}',
    deliveryGapReached: 'Free delivery reached',
    buyListEntry: 'Buy list for these orders',
    buyListTitle: 'Buy list',
    buyListIntro: 'One order per shop. Tick each book once it is in that shop’s cart.',
    buyListOrder: 'Order at {shop}',
    buyListOpen: 'Open ↗',
    buyListOpenLabel: 'Open {title} on {shop}',
    buyListNoLink: 'no listing link',
    buyListTickLabel: 'In the cart: {title}',
    buyListLibrisCart: 'Add to Libris cart ↗',
    buyListLibrisCartLabel: 'Add {title} to your Libris cart',
    buyListLibrisCartNote: 'The Libris link adds the book to your own Libris cart, in your browser.',
    buyListOpenNext: 'Open next: {title} at {shop}',
    buyListOpenedCount: '{opened} of {total} opened',
    buyListAllOpened: 'All listings opened',
    buyListStartAgain: 'Start again',
    buyListStepperNote: 'One tab per tap: browsers block several tabs from one tap.',
    buyListShare: 'Copy share link',
    buyListShareHint: 'The link holds the whole list. Ticks stay in this browser.',
    buyListShareLabel: 'Share link',
    buyListCopied: 'Link copied',
    buyListInvalid: 'This buy list link can’t be read.',
    buyListBack: 'Back to results',
    membershipsTitle: 'Memberships',
    membershipsIntro: 'Tick the memberships you have. A membership changes your total only when the shop\'s own rules page says so.',
    membershipDeclare: 'I have {name}',
    membershipNone: '{name} does not change delivery to Romania. Free delivery to Romania starts at {rule} ({threshold} lei) for everyone, {name} members included.',
    membershipNoneNoRule: '{name} does not change delivery to Romania.',
    membershipUnknown: '{name}: rules not printed. The {shop} rules page could not be read, so nothing is assumed.',
    membershipThreshold: 'With {name}, free delivery at {shop} starts at {threshold} lei.',
    membershipTotalsSame: 'Your totals do not change.',
    membershipSourceRead: 'Source: {url}, read {date}',
    membershipSourceTried: 'Read tried: {url}, {date}',
    monthsShort: 'Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec',
  },
  ro: {
    deliveryGapShort: 'Mai ai {amount} lei până la livrarea gratuită la {shop}',
    deliveryGapReached: 'Comanda are livrare gratuită',
    buyListEntry: 'Lista de cumpărături pentru aceste comenzi',
    buyListTitle: 'Lista de cumpărături',
    buyListIntro: 'O comandă pentru fiecare magazin. Bifează fiecare carte după ce e în coșul magazinului.',
    buyListOrder: 'Comanda la {shop}',
    buyListOpen: 'Deschide ↗',
    buyListOpenLabel: 'Deschide {title} la {shop}',
    buyListNoLink: 'fără link către pagina cărții',
    buyListTickLabel: 'În coș: {title}',
    buyListLibrisCart: 'Adaugă în coșul Libris ↗',
    buyListLibrisCartLabel: 'Adaugă {title} în coșul tău Libris',
    buyListLibrisCartNote: 'Linkul Libris adaugă cartea în coșul tău Libris, în browserul tău.',
    buyListOpenNext: 'Deschide următoarea: {title} la {shop}',
    buyListOpenedCount: '{opened} din {total} deschise',
    buyListAllOpened: 'Toate paginile au fost deschise',
    buyListStartAgain: 'Ia-o de la capăt',
    buyListStepperNote: 'Câte o filă la fiecare atingere: browserele blochează mai multe file deschise dintr-o singură atingere.',
    buyListShare: 'Copiază linkul de partajare',
    buyListShareHint: 'Linkul conține toată lista. Bifele rămân în acest browser.',
    buyListShareLabel: 'Link de partajare',
    buyListCopied: 'Link copiat',
    buyListInvalid: 'Linkul acestei liste nu poate fi citit.',
    buyListBack: 'Înapoi la rezultate',
    membershipsTitle: 'Abonamente',
    membershipsIntro: 'Bifează abonamentele pe care le ai. Un abonament schimbă totalul doar când pagina de reguli a magazinului spune asta.',
    membershipDeclare: 'Am {name}',
    membershipNone: '{name} nu schimbă livrarea în România. Livrarea gratuită în România începe de la {rule} ({threshold} lei) pentru toată lumea, inclusiv pentru membrii {name}.',
    membershipNoneNoRule: '{name} nu schimbă livrarea în România.',
    membershipUnknown: '{name}: regulile nu sunt afișate. Pagina de reguli {shop} nu a putut fi citită, așa că nu presupunem nimic.',
    membershipThreshold: 'Cu {name}, livrarea gratuită la {shop} începe de la {threshold} lei.',
    membershipTotalsSame: 'Totalurile nu se schimbă.',
    membershipSourceRead: 'Sursa: {url}, citită pe {date}',
    membershipSourceTried: 'Citire încercată: {url}, pe {date}',
    monthsShort: 'ian. feb. mar. apr. mai iun. iul. aug. sept. oct. nov. dec.',
  },
};

export function fill(template: string, values: Record<string, string>): string {
  return template.replace(/\{(\w+)\}/g, (whole, key: string) => (key in values ? values[key] : whole));
}
