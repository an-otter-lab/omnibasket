// RO and EN copy. Feature 8 moves the rest of the app's copy here and adds the
// browser-language default and the toggle. Until then the app runs in 'en'.
// Rules: "order" in EN, "comandă" in RO, never the old word for it.
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

  // Feature 1: the one box.
  boxPlaceholder: string;
  boxFind: string;
  boxSample: string;
  tabOne: string;
  /** {n} */
  tabMany: string;
  tabCheapest: string;

  pickTitle: string;
  pickRead: string;
  /** {shops} */
  pickListed: string;
  pickNoIsbn: string;
  pickEmpty: string;
  pickSearching: string;
  pickSearchError: string;
  pickLinkFail: string;
  pickLinkFailHint: string;
  /** {isbn} */
  pickIsbnTitle: string;
  pickIsbnNote: string;

  /** {title} */
  progTitle: string;
  progWait: string;
  progFailed: string;
  progRetry: string;
  progLineReading: string;
  progLineOk: string;
  progLineFailed: string;
  progLineSkipped: string;

  readsTitle: string;
  readsRanked: string;
  readsNotCompared: string;
  /** {shop} */
  readsRefused: string;
  readsRefusedLine: string;
  readsNoOffer: string;
  readsNoPrice: string;
  /** {shop} */
  readsNotLive: string;
  readsCheckAmazon: string;
  /** {shop} */
  readsOpen: string;
  /** {shop} */
  readsSearch: string;
  readsNoLink: string;
  readsOther: string;
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
    boxPlaceholder: 'Type a title, author or ISBN, or paste a link.',
    boxFind: 'Find',
    boxSample: 'Try a sample basket',
    tabOne: '1 order',
    tabMany: '{n} orders',
    tabCheapest: 'cheapest',
    pickTitle: 'Which book?',
    pickRead: 'Read prices',
    pickListed: 'In our index at {shops}',
    pickNoIsbn: 'No ISBN in our index. Paste the ISBN to read its prices.',
    pickEmpty: 'Nothing in our index matches that. Try the ISBN, or paste a link.',
    pickSearching: 'Searching…',
    pickSearchError: 'Search didn’t answer. Try again in a moment.',
    pickLinkFail: "I couldn't find a book on that page.",
    pickLinkFailHint: 'Paste the book’s ISBN or type its title instead.',
    pickIsbnTitle: 'ISBN {isbn}',
    pickIsbnNote: 'Not in our index. We can still read the shops for this ISBN.',
    progTitle: 'Reading prices for {title}',
    progWait: 'Each shop is read live, so this takes a few seconds.',
    progFailed: 'The read didn’t finish. Nothing was guessed.',
    progRetry: 'Try again',
    progLineReading: 'reading',
    progLineOk: 'read',
    progLineFailed: 'not read',
    progLineSkipped: 'skipped',
    readsTitle: 'What each shop said',
    readsRanked: 'Priced and compared',
    readsNotCompared: 'Price read. Delivery rules not read, so it is left out of the comparison.',
    readsRefused: "Couldn't read {shop} right now",
    readsRefusedLine: 'Its page didn’t load. Nothing was guessed.',
    readsNoOffer: 'No offer found for this ISBN',
    readsNoPrice: 'Found the page, couldn’t read a price',
    readsNotLive: '{shop} isn’t read live.',
    readsCheckAmazon: 'Check on Amazon.de',
    readsOpen: 'Open {shop} ↗',
    readsSearch: 'Search {shop} for this ISBN ↗',
    readsNoLink: 'no link',
    readsOther: 'Not read',
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
    boxPlaceholder: 'Scrie un titlu, un autor sau un ISBN, sau lipește un link.',
    boxFind: 'Caută',
    boxSample: 'Încearcă un coș de probă',
    tabOne: '1 comandă',
    tabMany: '{n} comenzi',
    tabCheapest: 'cea mai ieftină',
    pickTitle: 'Care carte?',
    pickRead: 'Citește prețurile',
    pickListed: 'În indexul nostru la {shops}',
    pickNoIsbn: 'Nu are ISBN în indexul nostru. Lipește ISBN-ul ca să-i citim prețurile.',
    pickEmpty: 'Nimic din indexul nostru nu se potrivește. Încearcă ISBN-ul sau lipește un link.',
    pickSearching: 'Caut…',
    pickSearchError: 'Căutarea nu a răspuns. Încearcă peste puțin timp.',
    pickLinkFail: 'Nu am găsit nicio carte pe pagina aceea.',
    pickLinkFailHint: 'Lipește ISBN-ul cărții sau scrie titlul.',
    pickIsbnTitle: 'ISBN {isbn}',
    pickIsbnNote: 'Nu e în indexul nostru. Putem totuși citi magazinele pentru acest ISBN.',
    progTitle: 'Citim prețurile pentru {title}',
    progWait: 'Fiecare magazin e citit pe loc, deci durează câteva secunde.',
    progFailed: 'Citirea nu s-a terminat. Nu am ghicit nimic.',
    progRetry: 'Încearcă din nou',
    progLineReading: 'se citește',
    progLineOk: 'citit',
    progLineFailed: 'necitit',
    progLineSkipped: 'sărit',
    readsTitle: 'Ce a spus fiecare magazin',
    readsRanked: 'Preț citit și comparat',
    readsNotCompared: 'Preț citit. Regulile de livrare nu au fost citite, deci nu intră în comparație.',
    readsRefused: 'Nu am putut citi {shop} acum',
    readsRefusedLine: 'Pagina nu s-a încărcat. Nu am ghicit nimic.',
    readsNoOffer: 'Nicio ofertă găsită pentru acest ISBN',
    readsNoPrice: 'Am găsit pagina, dar nu am putut citi un preț',
    readsNotLive: '{shop} nu se citește pe loc.',
    readsCheckAmazon: 'Verifică pe Amazon.de',
    readsOpen: 'Deschide {shop} ↗',
    readsSearch: 'Caută pe {shop} acest ISBN ↗',
    readsNoLink: 'fără link',
    readsOther: 'Necitit',
  },
};

export function fill(template: string, values: Record<string, string>): string {
  return template.replace(/\{(\w+)\}/g, (whole, key: string) => (key in values ? values[key] : whole));
}
