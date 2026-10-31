// RO and EN copy. Every user-facing string in ui/src lives here (feature 8);
// i18n.ts picks the language (browser default, RO/EN toggle, localStorage).
// Shop names and book titles are proper nouns and stay as they are; text the API
// sends (reasons) is shown as sent.
// Rules: "order" in EN, "comandă" in RO, never the old word for it.
// Romanian uses comma-below ș/ț (U+0219/U+021B), never the cedilla forms (U+015F/U+0163).

export type Lang = 'en' | 'ro';

export interface Messages {
  /** {amount} is already formatted as the app formats lei (e.g. 153,50). */
  deliveryGapShort: string;
  deliveryGapReached: string;
  /** R8/R8b: the label above the /why paragraph; the paragraph itself comes from the API. */
  whyTitle: string;

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
  readsNotChecked: string;
  pickOpenShop: string;
  pickOpenListing: string;
  notCheckedLabel: string;
  readsNoPrice: string;
  /** {shop} */
  readsNotLive: string;
  readsCheckAmazon: string;
  /** {shop} */
  readsOpen: string;
  /** {shop} */
  readsSearch: string;
  readsNoLink: string;
  readsNoOfferAnywhere: string;
  readsOther: string;
  /** {shop} {isbn} */
  readsOtherPrinting: string;
  sampleTitle: string;
  basketTitle: string;
  basketEmptyTitle: string;
  basketEmptyNote: string;
  basketAddBook: string;
  basketRemove: string;
  basketClear: string;
  basketLeftOut: string;
  basketBooksTitle: string;
  sampleNote: string;
  demoBadge: string;
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

  // Feature 2: photo of a reading list.
  photoButton: string;
  photoButtonFull: string;
  photoAriaLabel: string;
  photoReading: string;
  /** {size} */
  photoOversize: string;
  photoReadFail: string;
  photoNotFoundTitle: string;
  /** {title} */
  photoPickEdition: string;
  photoPick: string;
  /** {n} */
  photoMatchedCount: string;
  /** {n} */
  photoAmbiguousCount: string;
  /** {n} */
  photoNotFoundCount: string;
  photoContinue: string;
  /** {size} */
  photoMaxSize: string;

  // Feature 8: settings (language and theme).
  prefsLabel: string;
  langLabel: string;
  langEn: string;
  langRo: string;
  /** Each language is named in itself. */
  langEnName: string;
  langRoName: string;
  themeLabel: string;
  themeSystem: string;
  themeLight: string;
  themeDark: string;

  // Feature 8: the rest of the app's copy.
  brand: string;
  /** {n}. One / 2-19 / 20+ (RO adds “de” from 20). */
  bookOne: string;
  bookMany: string;
  bookMany20: string;
  editionOne: string;
  editionMany: string;
  editionMany20: string;
  orderOne: string;
  orderMany: string;
  orderMany20: string;
  tryOne: string;
  tryMany: string;
  tryMany20: string;
  movedOne: string;
  movedMany: string;
  movedMany20: string;
  photoBooksOne: string;
  photoBooksMany: string;
  photoBooksMany20: string;
  openArrow: string;
  /** {shop} */
  openOn: string;
  /** {shop} */
  openOnArrow: string;
  /** {title} {shop} */
  openBookOn: string;
  noTotal: string;
  moved: string;
  /** {amount} */
  deliveryAmount: string;
  /** {amount} */
  feeAmount: string;
  deliveryNotPrinted: string;
  notRankedTitle: string;
  /** {amount} */
  booksLei: string;
  /** {shops} */
  notRankedNote: string;
  edit: string;
  loadFailTitle: string;
  loadFailNote: string;
  tryAgain: string;
  readingShops: string;
  addLabel: string;
  addPlaceholder: string;
  addNone: string;
  isbnNotPrinted: string;
  firstFoundAt: string;
  anyEdition: string;
  removeFromBasket: string;
  addToBasket: string;
  /** {n} */
  inBasket: string;
  seeOrders: string;
  /** {n} — the header basket pill's accessible name */
  headerOrdersLabel: string;
  back: string;
  /** {shop} */
  inCheapestPlan: string;
  deliveryOnOrder: string;
  otherShops: string;
  editionNotPrinted: string;
  readMatch: string;
  /** {fields} */
  readMismatch: string;
  bookPricesOnly: string;
  bookMissing: string;
  orders: string;
  /** {date} */
  readStamp: string;
  /** {shop} */
  insideOrder: string;
  /** {shop} */
  openEachToCart: string;
  /** {amount} */
  freeDeliveryFrom: string;
  /** {amount} */
  thisOrder: string;
  /** {amount} */
  overBy: string;
  /** {amount} */
  shortBy: string;
  rowBooks: string;
  rowDelivery: string;
  rowFee: string;
  notPrinted: string;
  rowTotal: string;
  orderMissing: string;
  /** {date} */
  triedStamp: string;
  /** {date} */
  checkedStamp: string;
  /** {shop} */
  couldntReadShop: string;
  /** {tries} */
  shopFailLoad: string;
  /** {date} {tries} */
  shopFailLoadWhen: string;
  /** {total} */
  shopFailCovers: string;
  aboutPricesRead: string;
  aboutPricesReadNote: string;
  /** {shop} */
  checkedCantPrice: string;
  /** {shop} {reason} */
  checkedCantPriceNote: string;
  shopMissing: string;
  tabsLabel: string;
  onlyWay: string;
  /** {shop} */
  onlyShop: string;
  notPossible: string;
  tabOrders: string;
  tabCustom: string;
  noOtherShop: string;
  tabCheapestHead: string;
  chooseStores: string;
  /** {value} */
  editionsPill: string;
  /** {n} */
  editionsPinned: string;
  editionsAny: string;
  oneBookTitle: string;
  /** {priced} {total} */
  oneOfBooksPricedTitle: string;
  /** {amount} */
  oneBookPrice: string;
  /** {amount} */
  plusDelivery: string;
  /** {amount} */
  notRankedBook: string;
  /** {shop} */
  onlyShopLists: string;
  /** {n} {shop} */
  allFromShop: string;
  /** {amount} */
  amountMore: string;
  thanCheapest: string;
  /** {shop} */
  openEachAt: string;
  whyNotSplit: string;
  /** {amount} */
  deltaFrom: string;
  /** {amount} */
  booksAmount: string;
  noSingleShop: string;
  customIntro: string;
  off: string;
  /** {shop} */
  useShop: string;
  sameAsCheapest: string;
  movedTitle: string;
  noTotalShops: string;
  workingSplit: string;
  deliveryIncluded: string;
  oneOrderCosts: string;
  shopsLeftOut: string;
  leftOutCouldntRead: string;
  /** {reason} */
  leftOutCantPrice: string;
  noRanked: string;
  editionsTitle: string;
  optionsTitle: string;
  onlyShopWith: string;
  onlyLastShop: string;
  cancel: string;
  any: string;
  notPossibleTitle: string;
  withEditions: string;
  /** {amount} {base} */
  editionsMore: string;
  /** {amount} {base} */
  editionsLess: string;
  editionsSame: string;
  /** {names} */
  edNotRankedBefore: string;
  cantBePriced: string;
  /** {amount} {shops} */
  edNotRankedAfter: string;
  apply: string;
  statusInPlan: string;
  statusCompared: string;
  statusFeesNotPrinted: string;
  statusNotListed: string;
  statusOutOfStock: string;
  statusCouldntRead: string;
  statusOtherEdition: string;
  editionPaperback: string;
  editionHardcover: string;
  editionBoardBook: string;
  fieldPrice: string;
  fieldTitle: string;
  fieldEdition: string;
  recordedNote: string;
  solveFailed: string;
  /** {date} */
  pricesRead: string;
  listAnd: string;
  progLabel: string;
  // Feature 7: Ask Omnibasket
  askTitle: string;
  /** R14: the visible label of the field; the placeholder is never the only label. */
  askLabel: string;
  askPlaceholder: string;
  /** R14: the longer hint under the field, wraps at 390. */
  askHint: string;
  askSubmit: string;
  askExample1: string;
  askExample2: string;
  askDoneTab: string;
  askDoneExclude: string;
  askDoneInclude: string;
  askDoneMembership: string;
  askDoneMembershipOff: string;
  askDonePinned: string;
  askDonePinsCleared: string;
  askPinsNotPossible: string;
  askUnsupported: string;
  askNotInBasket: string;
  askOneNotPossible: string;
  askUnavailable: string;
  askBusy: string;
  askMadeByMuse: string;
  
  // Entry screen v2
  entryHeadline: string;
  entrySubtitle: string;
  entryFieldLabel: string;
  entrySubmit: string;
  entryPhoto: string;
  entryHowItWorks: string;
  entryStep1: string;
  entryStep2: string;
  entryStep3: string;
  entryFootnote: string;
  menuLangLabel: string;
  menuThemeLabel: string;
  menuSystem: string;
  menuLight: string;
  menuDark: string;
  entryNoOffer: string;
  entryTryAnother: string;
  entrySearchShop: string;
  entryPlaceholder: string;
  entryPhotoPlaceholder: string;

  // R0/R4: the add-book state (#/add and #/find/<q>).
  addFindLabel: string;
  /** {title} {books} */
  addedToBasket: string;
  /** {title} */
  addReadFailed: string;
  /** R12: a pick of the same normalised title and author under another ISBN. */
  addDuplicateAsk: string;
  addDuplicateAdd: string;
  addDuplicateKeep: string;
  pickClear: string;
}

export const MESSAGES: Record<Lang, Messages> = {
  en: {
    deliveryGapShort: '{amount} lei short of free delivery at {shop}',
    deliveryGapReached: 'Free delivery reached',
    whyTitle: 'Why this split',
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
    pickListed: 'Found at {shops}',
    pickNoIsbn: 'Not found in our shops yet.',
    pickEmpty: 'No match. Try the book title or paste a link.',
    pickSearching: 'Searching…',
    pickSearchError: 'Search isn’t available right now. Try again in a moment.',
    pickLinkFail: "I couldn't find a book on that page.",
    pickLinkFailHint: 'Try typing the book title instead.',
    pickIsbnTitle: 'ISBN {isbn}',
    pickIsbnNote: 'We can still check the shops for this ISBN.',
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
    readsNotChecked: 'Not checked here',
    pickOpenShop: 'Open shop ↗',
    pickOpenListing: 'Open {shop} listing, new tab',
    notCheckedLabel: 'Not checked:',
    readsNoPrice: 'Found the page, couldn’t read a price',
    readsNotLive: '{shop} isn’t read live.',
    readsCheckAmazon: 'Check on Amazon.de',
    readsOpen: 'Open {shop} ↗',
    readsSearch: 'Search {shop} for this ISBN ↗',
    readsNoLink: 'no link',
    readsNoOfferAnywhere: 'No shop lists this ISBN.',
    readsOther: 'Not read',
    readsOtherPrinting: '{shop}: other printing, ISBN {isbn}',
    sampleTitle: 'Your sample basket',
    basketTitle: 'Your basket',
    basketEmptyTitle: 'Your basket is empty',
    basketEmptyNote: 'Find a book by title, ISBN or link and it will appear here.',
    basketAddBook: 'Add a book',
    basketRemove: 'Remove',
    basketClear: 'Clear basket',
    basketLeftOut: 'Left out of the totals: no shop with known delivery rules lists it.',
    basketBooksTitle: 'Your books, shop by shop',
    sampleNote: 'A demo basket of books. Its totals are for the whole basket, not the price of the book you picked. That is in the shop rows above.',
    demoBadge: 'Demo data',
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
    photoButton: 'Photo',
    photoButtonFull: 'Photo of a list',
    photoAriaLabel: 'Take or choose a photo of a reading list',
    photoReading: 'Reading the photo\u2026',
    photoOversize: 'This photo is over {size}. Try a smaller one.',
    photoReadFail: 'couldn\u2019t read this photo, try again',
    photoNotFoundTitle: 'not found in these shops',
    photoPickEdition: 'Which edition of {title}?',
    photoPick: 'Pick',
    photoMatchedCount: '{n} matched',
    photoAmbiguousCount: '{n} to pick',
    photoNotFoundCount: '{n} not found',
    photoContinue: 'Add to basket',
    photoMaxSize: '4\u202fMB',
    prefsLabel: 'Settings',
    langLabel: 'Language',
    langEn: 'EN',
    langRo: 'RO',
    langEnName: 'English',
    langRoName: 'Română',
    themeLabel: 'Theme',
    themeSystem: 'System',
    themeLight: 'Light',
    themeDark: 'Dark',
    brand: 'omnibasket',
    bookOne: '{n} book',
    bookMany: '{n} books',
    bookMany20: '{n} books',
    editionOne: '{n} edition',
    editionMany: '{n} editions',
    editionMany20: '{n} editions',
    orderOne: '{n} order',
    orderMany: '{n} orders',
    orderMany20: '{n} orders',
    tryOne: '{n} try',
    tryMany: '{n} tries',
    tryMany20: '{n} tries',
    movedOne: '{n} book moved',
    movedMany: '{n} books moved',
    movedMany20: '{n} books moved',
    photoBooksOne: '{n} book from photo',
    photoBooksMany: '{n} books from photo',
    photoBooksMany20: '{n} books from photo',
    openArrow: 'Open ↗',
    openOn: 'Open on {shop}',
    openOnArrow: 'Open on {shop} ↗',
    openBookOn: 'Open {title} on {shop}',
    noTotal: 'no total',
    moved: 'moved',
    deliveryAmount: 'Delivery {amount}',
    feeAmount: '+ fee {amount}',
    deliveryNotPrinted: 'delivery not printed',
    notRankedTitle: 'Another split, not ranked',
    booksLei: 'books {amount} lei',
    notRankedNote: '{shops} does not print its delivery under the free-delivery line, so this split has no total.',
    edit: 'Edit',
    loadFailTitle: 'We couldn’t load the shops.',
    loadFailNote: 'Nothing was guessed. Try again in a moment.',
    tryAgain: 'Try again',
    readingShops: 'Reading the shops…',
    addLabel: 'Book title or ISBN',
    addPlaceholder: 'e.g. Where the Wild Things Are',
    addNone: 'Not in the shops we read.',
    isbnNotPrinted: 'ISBN not printed',
    firstFoundAt: 'First found at',
    anyEdition: 'Any edition',
    removeFromBasket: 'Remove from basket',
    addToBasket: 'Add to basket',
    inBasket: 'In your basket · {n}',
    seeOrders: 'See orders',
    headerOrdersLabel: '{n} · see your orders',
    back: 'Back',
    inCheapestPlan: 'In your cheapest plan · {shop}',
    deliveryOnOrder: 'delivery counted on the order',
    otherShops: 'Other shops for this book',
    editionNotPrinted: 'edition not printed',
    readMatch: 'Read by Muse Spark · matches the page',
    readMismatch: 'doesn’t match the page · {fields}',
    bookPricesOnly: 'Book prices only. What you pay for postage depends on the whole order.',
    bookMissing: 'This book is not in the shops we read.',
    orders: 'Orders',
    readStamp: 'read {date}',
    insideOrder: 'Inside the {shop} order',
    openEachToCart: 'Open each book to add it to your {shop} cart. We can’t fill shop carts for you.',
    freeDeliveryFrom: 'Free delivery from {amount}',
    thisOrder: 'this order {amount}',
    overBy: '{amount} over',
    shortBy: '{amount} short',
    rowBooks: 'Books',
    rowDelivery: 'Delivery',
    rowFee: 'Order fee',
    notPrinted: 'not printed',
    rowTotal: 'Order total',
    orderMissing: 'That order is not in this answer.',
    triedStamp: 'tried {date}',
    checkedStamp: 'checked {date}',
    couldntReadShop: 'We couldn’t read {shop}',
    shopFailLoad: 'Its pages didn’t load ({tries}). It isn’t part of your orders.',
    shopFailLoadWhen: 'Its pages didn’t load when we tried on {date} ({tries}). It isn’t part of your orders.',
    shopFailCovers: 'The {total} covers the shops we could read.',
    aboutPricesRead: 'About “prices read”',
    aboutPricesReadNote: 'Every order shows when its shop was read. Shops change prices now and then, so check again before you order.',
    checkedCantPrice: '{shop}: checked, can’t be priced',
    checkedCantPriceNote: 'Some books look cheaper here. Without the delivery and order fee we can’t tell whether the order is, so we leave {shop} out rather than guess. Reason: {reason}.',
    shopMissing: 'That shop is not in this answer.',
    tabsLabel: 'Ways to buy',
    onlyWay: 'only way',
    onlyShop: '{shop} only',
    notPossible: 'not possible',
    tabOrders: 'orders',
    tabCustom: 'Custom',
    noOtherShop: 'no other shop',
    tabCheapestHead: 'Cheapest',
    chooseStores: 'choose stores',
    editionsPill: 'Editions: {value}',
    editionsPinned: '{n} pinned',
    editionsAny: 'any',
    oneBookTitle: 'One book, one order. Which shop?',
    /** {priced} {total} */
    oneOfBooksPricedTitle: '{priced} of {total} books priced. Which shop?',
    oneBookPrice: 'book {amount} · delivery and fees included in the total',
    plusDelivery: '{amount} + delivery',
    notRankedBook: 'Not ranked: delivery not printed. Book {amount}, no total.',
    onlyShopLists: 'Only {shop} lists all of them · delivery included',
    allFromShop: 'All {n} from {shop} in one order ·',
    amountMore: '{amount} more',
    thanCheapest: 'than the cheapest',
    openEachAt: 'Open each book at {shop}',
    whyNotSplit: 'Why not a split into orders?',
    deltaFrom: 'Where the {amount} comes from',
    booksAmount: 'Books {amount}',
    noSingleShop: 'No single shop',
    customIntro: 'Switch off shops you’d rather not use. Their books move to the shops you keep, the cheapest way.',
    off: 'Off',
    useShop: 'Use {shop}',
    sameAsCheapest: 'same as the cheapest',
    movedTitle: 'Moved',
    noTotalShops: 'No total for these shops',
    workingSplit: 'Working out the split…',
    deliveryIncluded: 'Delivery included',
    oneOrderCosts: 'one order costs',
    shopsLeftOut: 'Shops left out',
    leftOutCouldntRead: 'Couldn’t read its pages · try again',
    leftOutCantPrice: 'Checked, can’t be priced: {reason}',
    noRanked: 'No ranked answer',
    editionsTitle: 'Editions',
    optionsTitle: 'Options',
    onlyShopWith: 'Only shop with {titles}',
    onlyLastShop: 'The only shop you chose',
    cancel: 'Cancel',
    any: 'Any',
    notPossibleTitle: 'Not possible',
    withEditions: 'With these editions',
    editionsMore: '{amount} more than any edition ({base}).',
    editionsLess: '{amount} less than any edition ({base}).',
    editionsSame: 'Same total as any edition.',
    edNotRankedBefore: 'Another split, {names},',
    cantBePriced: 'can’t be priced',
    edNotRankedAfter: ': books {amount}, {shops} doesn’t print delivery under its free-delivery line. No total.',
    apply: 'Apply',
    statusInPlan: 'In your plan',
    statusCompared: 'Compared',
    statusFeesNotPrinted: 'Fees not printed, not compared',
    statusNotListed: 'Not listed',
    statusOutOfStock: 'Out of stock',
    statusCouldntRead: 'Couldn’t read',
    statusOtherEdition: 'Another edition',
    editionPaperback: 'Paperback',
    editionHardcover: 'Hardcover',
    editionBoardBook: 'Board book',
    fieldPrice: 'price',
    fieldTitle: 'title',
    fieldEdition: 'edition',
    recordedNote: 'This is a recorded example. Changes are not re-solved.',
    solveFailed: 'The solve failed.',
    pricesRead: 'prices read {date}',
    listAnd: 'and',
    progLabel: 'Read progress',
    // Feature 7: Ask Omnibasket
    askTitle: 'Ask Omnibasket',
    askLabel: 'Ask',
    askPlaceholder: 'Ask, e.g. "no Amazon"',
    askHint: 'Try: no Amazon · keep it to one order',
    askSubmit: 'Ask',
    askExample1: 'Keep it to one order',
    askExample2: 'No Amazon',
    askDoneTab: 'Showing {tab}.',
    askDoneExclude: 'Left out {shop}.',
    askDoneInclude: 'Added {shop} back.',
    askDoneMembership: 'Counted your {name}.',
    askDoneMembershipOff: 'No longer counting {name}.',
    askDonePinned: 'Pinned {n} books to the editions in this answer.',
    askDonePinsCleared: 'Any edition is fine again.',
    askPinsNotPossible: 'Those exact editions cannot be bought together, so I left your editions as they were.',
    askUnsupported: 'I can’t do that yet.',
    askNotInBasket: '{shop} isn’t part of this basket.',
    askOneNotPossible: 'One order isn’t possible: no single shop lists every book.',
    askUnavailable: 'Ask is not available right now.',
    askBusy: 'Too many questions at once. Try again in a minute.',
    askMadeByMuse: 'Understood by Muse',
    entryHeadline: 'One order, or the cheapest?',
    entrySubtitle: 'List the books. We\'ll show what each way of buying them costs, with postage in and nothing guessed.',
    entryFieldLabel: 'Book title or ISBN',
    entrySubmit: 'Find book',
    entryPhoto: 'Photo of a list',
    entryHowItWorks: 'How it works',
    entryStep1: 'Add books by title or ISBN.',
    entryStep2: 'We read each shop\'s prices, postage and free-delivery thresholds.',
    entryStep3: 'Pick one order, the cheapest split, or your own shops.',
    entryFootnote: 'We read and index shop data from a few sources. Where a shop does not publish a fee, we leave it blank rather than guess.',
    menuLangLabel: 'Language',
    menuThemeLabel: 'Theme',
    menuSystem: 'System',
    menuLight: 'Light',
    menuDark: 'Dark',
    entryNoOffer: 'No shop lists this ISBN.',
    entryTryAnother: 'Try another edition',
    entrySearchShop: 'Search this shop',
    entryPlaceholder: 'e.g. Room on the Broom',
    entryPhotoPlaceholder: 'Photo of a list',
    addFindLabel: 'Find a book',
    addedToBasket: 'Added {title}. {books} in your basket.',
    addReadFailed: 'Couldn’t read prices for {title}. Try again.',
    addDuplicateAsk: 'You already have this book (different edition). Add it anyway?',
    addDuplicateAdd: 'Add anyway',
    addDuplicateKeep: 'Keep one',
    pickClear: 'Clear',
  },
  ro: {
    deliveryGapShort: 'Mai ai {amount} lei până la livrarea gratuită la {shop}',
    deliveryGapReached: 'Comanda are livrare gratuită',
    whyTitle: 'De ce această împărțire',
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
    pickListed: 'Găsit la {shops}',
    pickNoIsbn: 'Nu este încă în magazinele noastre.',
    pickEmpty: 'Nicio potrivire. Încearcă titlul cărții sau lipește un link.',
    pickSearching: 'Caut…',
    pickSearchError: 'Căutarea nu a răspuns. Încearcă peste puțin timp.',
    pickLinkFail: 'Nu am găsit nicio carte pe pagina aceea.',
    pickLinkFailHint: 'Încearcă să scrii titlul cărții.',
    pickIsbnTitle: 'ISBN {isbn}',
    pickIsbnNote: 'Putem totuși verifica magazinele pentru acest ISBN.',
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
    readsNotChecked: 'Nu a fost verificat aici',
    pickOpenShop: 'Deschide magazinul ↗',
    pickOpenListing: 'Deschide anunțul {shop}, filă nouă',
    notCheckedLabel: 'Neverificate:',
    readsNoPrice: 'Am găsit pagina, dar nu am putut citi un preț',
    readsNotLive: '{shop} nu se citește pe loc.',
    readsCheckAmazon: 'Verifică pe Amazon.de',
    readsOpen: 'Deschide {shop} ↗',
    readsSearch: 'Caută pe {shop} acest ISBN ↗',
    readsNoLink: 'fără link',
    readsNoOfferAnywhere: 'Niciun magazin nu are acest ISBN.',
    readsOther: 'Necitit',
    readsOtherPrinting: '{shop}: altă tipărire, ISBN {isbn}',
    sampleTitle: 'Coșul demo',
    basketTitle: 'Coșul tău',
    basketEmptyTitle: 'Coșul e gol',
    basketEmptyNote: 'Caută o carte după titlu, ISBN sau link și apare aici.',
    basketAddBook: 'Adaugă o carte',
    basketRemove: 'Scoate',
    basketClear: 'Golește coșul',
    basketLeftOut: 'Nu intră în totaluri: niciun magazin cu reguli de livrare cunoscute nu o are.',
    basketBooksTitle: 'Cărțile tale, magazin cu magazin',
    sampleNote: 'Un coș demo de cărți. Totalurile sunt pentru tot coșul, nu prețul cărții alese. Acela e în rândurile magazinelor de mai sus.',
    demoBadge: 'Date demo',
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
    photoButton: 'Fotografie',
    photoButtonFull: 'Fotografie a unei liste',
    photoAriaLabel: 'Fă sau alege o fotografie a unei liste de cărți',
    photoReading: 'Citesc fotografia\u2026',
    photoOversize: 'Fotografia depășește {size}. Încearcă una mai mică.',
    photoReadFail: 'nu am putut citi fotografia, încearcă din nou',
    photoNotFoundTitle: 'nu se găsesc în aceste magazine',
    photoPickEdition: 'Care ediție din {title}?',
    photoPick: 'Alege',
    photoMatchedCount: '{n} potrivite',
    photoAmbiguousCount: '{n} de ales',
    photoNotFoundCount: '{n} negăsite',
    photoContinue: 'Adaugă în coș',
    photoMaxSize: '4\u202fMO',
    prefsLabel: 'Setări',
    langLabel: 'Limba',
    langEn: 'EN',
    langRo: 'RO',
    langEnName: 'English',
    langRoName: 'Română',
    themeLabel: 'Temă',
    themeSystem: 'Sistem',
    themeLight: 'Luminoasă',
    themeDark: 'Întunecată',
    brand: 'omnibasket',
    bookOne: '{n} carte',
    bookMany: '{n} cărți',
    bookMany20: '{n} de cărți',
    editionOne: '{n} ediție',
    editionMany: '{n} ediții',
    editionMany20: '{n} de ediții',
    orderOne: '{n} comandă',
    orderMany: '{n} comenzi',
    orderMany20: '{n} de comenzi',
    tryOne: '{n} încercare',
    tryMany: '{n} încercări',
    tryMany20: '{n} de încercări',
    movedOne: '{n} carte mutată',
    movedMany: '{n} cărți mutate',
    movedMany20: '{n} de cărți mutate',
    photoBooksOne: '{n} carte din fotografie',
    photoBooksMany: '{n} cărți din fotografie',
    photoBooksMany20: '{n} de cărți din fotografie',
    openArrow: 'Deschide ↗',
    openOn: 'Deschide la {shop}',
    openOnArrow: 'Deschide la {shop} ↗',
    openBookOn: 'Deschide {title} la {shop}',
    noTotal: 'fără total',
    moved: 'mutată',
    deliveryAmount: 'Livrare {amount}',
    feeAmount: '+ taxă {amount}',
    deliveryNotPrinted: 'livrarea nu e afișată',
    notRankedTitle: 'Altă împărțire, neclasată',
    booksLei: 'cărți {amount} lei',
    notRankedNote: '{shops} nu afișează livrarea sub pragul de livrare gratuită, deci această împărțire nu are total.',
    edit: 'Editează',
    loadFailTitle: 'Nu am putut încărca magazinele.',
    loadFailNote: 'Nu am ghicit nimic. Încearcă din nou peste puțin timp.',
    tryAgain: 'Încearcă din nou',
    readingShops: 'Citim magazinele…',
    addLabel: 'Titlul cărții sau ISBN',
    addPlaceholder: 'ex. Where the Wild Things Are',
    addNone: 'Nu e în magazinele pe care le citim.',
    isbnNotPrinted: 'ISBN neafișat',
    firstFoundAt: 'Găsită prima dată la',
    anyEdition: 'Orice ediție',
    removeFromBasket: 'Scoate din coș',
    addToBasket: 'Adaugă în coș',
    inBasket: 'În coșul tău · {n}',
    seeOrders: 'Vezi comenzile',
    headerOrdersLabel: '{n} · vezi comenzile',
    back: 'Înapoi',
    inCheapestPlan: 'În planul cel mai ieftin · {shop}',
    deliveryOnOrder: 'livrarea se socotește pe comandă',
    otherShops: 'Alte magazine pentru această carte',
    editionNotPrinted: 'ediția nu e afișată',
    readMatch: 'Citit de Muse Spark · se potrivește cu pagina',
    readMismatch: 'nu se potrivește cu pagina · {fields}',
    bookPricesOnly: 'Doar prețurile cărților. Cât plătești pentru livrare depinde de toată comanda.',
    bookMissing: 'Cartea aceasta nu e în magazinele pe care le citim.',
    orders: 'Comenzi',
    readStamp: 'citit {date}',
    insideOrder: 'Ce e în comanda de la {shop}',
    openEachToCart: 'Deschide fiecare carte ca s-o adaugi în coșul tău {shop}. Nu putem umple coșurile magazinelor în locul tău.',
    freeDeliveryFrom: 'Livrare gratuită de la {amount}',
    thisOrder: 'această comandă {amount}',
    overBy: 'cu {amount} peste',
    shortBy: 'lipsesc {amount}',
    rowBooks: 'Cărți',
    rowDelivery: 'Livrare',
    rowFee: 'Taxă de comandă',
    notPrinted: 'neafișat',
    rowTotal: 'Totalul comenzii',
    orderMissing: 'Comanda aceea nu e în acest răspuns.',
    triedStamp: 'încercat {date}',
    checkedStamp: 'verificat {date}',
    couldntReadShop: 'Nu am putut citi {shop}',
    shopFailLoad: 'Paginile nu s-au încărcat ({tries}). Nu face parte din comenzile tale.',
    shopFailLoadWhen: 'Paginile nu s-au încărcat când am încercat pe {date} ({tries}). Nu face parte din comenzile tale.',
    shopFailCovers: 'Totalul de {total} acoperă magazinele pe care le-am putut citi.',
    aboutPricesRead: 'Despre „prețuri citite”',
    aboutPricesReadNote: 'Fiecare comandă arată când i-a fost citit magazinul. Magazinele schimbă prețurile din când în când, așa că verifică din nou înainte să comanzi.',
    checkedCantPrice: '{shop}: verificat, nu poate fi calculat',
    checkedCantPriceNote: 'Unele cărți par mai ieftine aici. Fără livrare și taxa de comandă nu putem spune dacă și comanda e mai ieftină, așa că lăsăm {shop} deoparte în loc să ghicim. Motiv: {reason}.',
    shopMissing: 'Magazinul acela nu e în acest răspuns.',
    tabsLabel: 'Moduri de cumpărare',
    onlyWay: 'singura variantă',
    onlyShop: 'doar {shop}',
    notPossible: 'imposibil',
    tabOrders: 'comenzi',
    tabCustom: 'Personalizat',
    noOtherShop: 'niciun alt magazin',
    tabCheapestHead: 'Cea mai ieftină',
    chooseStores: 'alege magazinele',
    editionsPill: 'Ediții: {value}',
    editionsPinned: '{n} fixate',
    editionsAny: 'oricare',
    oneBookTitle: 'O carte, o comandă. Care magazin?',
    /** {priced} {total} */
    oneOfBooksPricedTitle: '{priced} din {total} cărți cu preț. Care magazin?',
    oneBookPrice: 'carte {amount} · livrarea și taxele sunt incluse în total',
    plusDelivery: '{amount} + livrare',
    notRankedBook: 'Neclasat: livrarea nu e afișată. Carte {amount}, fără total.',
    onlyShopLists: 'Doar {shop} le are pe toate · livrare inclusă',
    allFromShop: 'Toate cele {n} de la {shop} într-o comandă ·',
    amountMore: 'cu {amount} mai mult',
    thanCheapest: 'decât cea mai ieftină',
    openEachAt: 'Deschide fiecare carte la {shop}',
    whyNotSplit: 'De ce nu o împărțire în comenzi?',
    deltaFrom: 'De unde vine diferența de {amount}',
    booksAmount: 'Cărți {amount}',
    noSingleShop: 'Niciun magazin nu le are pe toate',
    customIntro: 'Oprește magazinele pe care nu vrei să le folosești. Cărțile lor se mută la magazinele rămase, în varianta cea mai ieftină.',
    off: 'Oprit',
    useShop: 'Folosește {shop}',
    sameAsCheapest: 'la fel ca cea mai ieftină',
    movedTitle: 'Mutate',
    noTotalShops: 'Niciun total pentru aceste magazine',
    workingSplit: 'Calculăm împărțirea…',
    deliveryIncluded: 'Livrare inclusă',
    oneOrderCosts: 'o singură comandă costă',
    shopsLeftOut: 'Magazine lăsate deoparte',
    leftOutCouldntRead: 'Nu i-am putut citi paginile · încearcă din nou',
    leftOutCantPrice: 'Verificat, nu poate fi calculat: {reason}',
    noRanked: 'Niciun răspuns clasat',
    editionsTitle: 'Ediții',
    optionsTitle: 'Opțiuni',
    onlyShopWith: 'Singurul magazin cu {titles}',
    onlyLastShop: 'Singurul magazin ales',
    cancel: 'Anulează',
    any: 'Oricare',
    notPossibleTitle: 'Imposibil',
    withEditions: 'Cu aceste ediții',
    editionsMore: 'Cu {amount} mai mult decât cu orice ediție ({base}).',
    editionsLess: 'Cu {amount} mai puțin decât cu orice ediție ({base}).',
    editionsSame: 'Același total ca pentru orice ediție.',
    edNotRankedBefore: 'Altă împărțire, {names},',
    cantBePriced: 'nu poate fi calculată',
    edNotRankedAfter: ': cărți {amount}, {shops} nu afișează livrarea sub pragul de livrare gratuită. Fără total.',
    apply: 'Aplică',
    statusInPlan: 'În planul tău',
    statusCompared: 'Comparat',
    statusFeesNotPrinted: 'Taxe neafișate, necomparat',
    statusNotListed: 'Nu e listată',
    statusOutOfStock: 'Stoc epuizat',
    statusCouldntRead: 'Nu am putut citi',
    statusOtherEdition: 'Altă ediție',
    editionPaperback: 'Copertă broșată',
    editionHardcover: 'Copertă cartonată',
    editionBoardBook: 'File cartonate',
    fieldPrice: 'preț',
    fieldTitle: 'titlu',
    fieldEdition: 'ediție',
    recordedNote: 'Acesta e un exemplu înregistrat. Modificările nu se recalculează.',
    solveFailed: 'Calculul nu a reușit.',
    pricesRead: 'prețuri citite {date}',
    listAnd: 'și',
    progLabel: 'Progresul citirii',
    // Feature 7: Ask Omnibasket
    askTitle: 'Întreabă Omnibasket',
    askLabel: 'Întreabă',
    askPlaceholder: 'Întreabă, ex. „fără Amazon”',
    askHint: 'Încearcă: fără Amazon · o singură comandă',
    askSubmit: 'Întreabă',
    askExample1: 'O singură comandă',
    askExample2: 'Fără Amazon',
    askDoneTab: 'Afișez: {tab}.',
    askDoneExclude: 'Am scos {shop}.',
    askDoneInclude: 'Am adăugat {shop} la loc.',
    askDoneMembership: 'Am luat în calcul {name}.',
    askDoneMembershipOff: 'Nu mai iau în calcul {name}.',
    askDonePinned: 'Am fixat {n} cărți la edițiile din acest răspuns.',
    askDonePinsCleared: 'Orice ediție e din nou bună.',
    askPinsNotPossible: 'Edițiile exacte nu se pot cumpăra împreună, așa că am lăsat edițiile cum erau.',
    askUnsupported: 'Încă nu pot face asta.',
    askNotInBasket: '{shop} nu face parte din acest coș.',
    askOneNotPossible: 'O singură comandă nu este posibilă: niciun magazin nu are toate cărțile.',
    askUnavailable: 'Întrebările nu sunt disponibile acum.',
    askBusy: 'Prea multe întrebări deodată. Încearcă din nou peste un minut.',
    askMadeByMuse: 'Înțeles de Muse',
    entryHeadline: 'O singură comandă, sau cea mai ieftină?',
    entrySubtitle: 'Înșiră cărțile. Îți arătăm cât te costă fiecare fel de a le cumpăra, cu poșta inclusă, fără să ghicim nimic.',
    entryFieldLabel: 'Titlu sau ISBN',
    entrySubmit: 'Caută cartea',
    entryPhoto: 'Fotografie a unei liste',
    entryHowItWorks: 'Cum funcționează',
    entryStep1: 'Adaugă cărți după titlu sau ISBN.',
    entryStep2: 'Citim din fiecare magazin prețurile, poșta și pragurile de livrare gratuită.',
    entryStep3: 'Alege o singură comandă, cea mai ieftină împărțire, sau magazinele tale.',
    entryFootnote: 'Citim și indexăm datele magazinelor din câteva surse. Unde un magazin nu publică o taxă, o lăsăm liberă în loc să o ghicim.',
    menuLangLabel: 'Limbă',
    menuThemeLabel: 'Temă',
    menuSystem: 'Sistem',
    menuLight: 'Luminoasă',
    menuDark: 'Întunecată',
    entryNoOffer: 'Niciun magazin nu are acest ISBN.',
    entryTryAnother: 'Încearcă altă ediție',
    entrySearchShop: 'Caută în acest magazin',
    entryPlaceholder: 'ex. Camera din Pădure',
    entryPhotoPlaceholder: 'Fotografie a unei liste',
    addFindLabel: 'Caută o carte',
    addedToBasket: 'Adăugat {title}. {books} în coș.',
    addReadFailed: 'Nu am putut citi prețurile pentru {title}. Încearcă din nou.',
    addDuplicateAsk: 'Ai deja cartea aceasta (altă ediție). O adaugi oricum?',
    addDuplicateAdd: 'Adaugă oricum',
    addDuplicateKeep: 'Păstrează una',
    pickClear: 'Șterge',
  },
};

export function fill(template: string, values: Record<string, string>): string {
  return template.replace(/\{(\w+)\}/g, (whole, key: string) => (key in values ? values[key] : whole));
}

type CountKey = 'book' | 'edition' | 'order' | 'try' | 'moved' | 'photoBooks';

/**
 * "{n} books" in either language. Romanian has three forms: 1 carte, 2-19 cărți,
 * 20+ (and 101-119 back to the middle form) "de cărți". English uses the first two.
 */
export function count(lang: Lang, n: number, key: CountKey): string {
  const m = MESSAGES[lang] as unknown as Record<string, string>;
  const rest = Math.abs(n) % 100;
  const form = n === 1 ? 'One' : lang === 'ro' && n !== 0 && (rest === 0 || rest >= 20) ? 'Many20' : 'Many';
  return fill(m[key + form], { n: String(n) });
}

const EDITION_KEY: Record<string, keyof Messages> = {
  paperback: 'editionPaperback',
  hardcover: 'editionHardcover',
  board_book: 'editionBoardBook',
};

/** An edition code from the API, named in the language. Unknown codes are shown tidied, not guessed. */
export function editionName(lang: Lang, code: string | null | undefined): string {
  if (!code) return '';
  const key = EDITION_KEY[code];
  if (key) return MESSAGES[lang][key];
  const t = code.replace(/_/g, ' ');
  return t.charAt(0).toUpperCase() + t.slice(1);
}

const FIELD_KEY: Record<string, keyof Messages> = {
  price: 'fieldPrice',
  title: 'fieldTitle',
  edition: 'fieldEdition',
};

/** A model-read field code, named in the language. */
export function fieldName(lang: Lang, code: string): string {
  if (code === 'isbn13') return 'ISBN';
  const key = FIELD_KEY[code];
  return key ? MESSAGES[lang][key] : code;
}
