/** Locked basket fields sent to POST /solve. Displayed money comes back from the API. */

export interface CatalogOffer {
  storeId: string;
  priceCents: number;
  sellerCertainty: string;
  seller: string;
  isbn13: string | null;
  deliveryWindow: string | null;
  sameStory: boolean;
}

export interface CatalogBook {
  id: string;
  title: string;
  isbn13: string | null;
  offers: CatalogOffer[];
}

export interface CatalogStore {
  id: string;
  name: string;
  currency: string;
  freeShippingThresholdCents: number;
  shippingFeeCents: number;
  perOrderFeeCents: number;
}

export const STORE_NAME: Record<string, string> = {
  libris: 'Libris',
  emag: 'eMAG',
  bookzone: 'Bookzone',
  amazon_de: 'Amazon.de',
};

export const CATALOG_STORES: CatalogStore[] = [
  { id: 'libris', name: 'Libris', currency: 'RON', freeShippingThresholdCents: 13500, shippingFeeCents: 1290, perOrderFeeCents: 0 },
  { id: 'emag', name: 'eMAG', currency: 'RON', freeShippingThresholdCents: 1000000000, shippingFeeCents: 0, perOrderFeeCents: 149 },
  { id: 'bookzone', name: 'Bookzone', currency: 'RON', freeShippingThresholdCents: 20000, shippingFeeCents: 690, perOrderFeeCents: 199 },
  { id: 'amazon_de', name: 'Amazon.de', currency: 'RON', freeShippingThresholdCents: 26217, shippingFeeCents: 2670, perOrderFeeCents: 0 },
];

export const CATALOG_BOOKS: CatalogBook[] = [
  {
    id: 'ghici',
    title: 'Ghici cât de mult te iubesc',
    isbn13: '9786068996011',
    offers: [
      { storeId: 'bookzone', priceCents: 4650, sellerCertainty: 'direct', seller: 'Bookzone', isbn13: '9786068996011', deliveryWindow: null, sameStory: false },
      { storeId: 'emag', priceCents: 5600, sellerCertainty: 'marketplace', seller: 'CARTEA COPIILOR', isbn13: '9786068996011', deliveryWindow: null, sameStory: false },
      { storeId: 'libris', priceCents: 5700, sellerCertainty: 'direct', seller: 'Libris', isbn13: '9786068996011', deliveryWindow: null, sameStory: false },
    ],
  },
  {
    id: 'vhc',
    title: 'The Very Hungry Caterpillar',
    isbn13: null,
    offers: [
      { storeId: 'emag', priceCents: 5753, sellerCertainty: 'marketplace', seller: 'Libris English SRL', isbn13: '9780241003008', deliveryWindow: null, sameStory: true },
      { storeId: 'libris', priceCents: 6133, sellerCertainty: 'direct', seller: 'Libris', isbn13: null, deliveryWindow: '2-4 saptamani', sameStory: true },
    ],
  },
  {
    id: 'owl',
    title: 'Owl Babies',
    isbn13: null,
    offers: [
      { storeId: 'libris', priceCents: 5178, sellerCertainty: 'direct', seller: 'Libris', isbn13: null, deliveryWindow: '2-4 saptamani', sameStory: true },
      { storeId: 'emag', priceCents: 15700, sellerCertainty: 'marketplace', seller: 'Karte', isbn13: '9780763695194', deliveryWindow: null, sameStory: true },
    ],
  },
  {
    id: 'mole',
    title: 'The Boy, the Mole, the Fox and the Horse',
    isbn13: '9781529105100',
    offers: [
      { storeId: 'amazon_de', priceCents: 11653, sellerCertainty: 'direct', seller: 'Amazon', isbn13: '9781529105100', deliveryWindow: null, sameStory: false },
      { storeId: 'libris', priceCents: 14256, sellerCertainty: 'direct', seller: 'Libris', isbn13: '9781529105100', deliveryWindow: null, sameStory: false },
    ],
  },
  {
    id: 'wild',
    title: 'Where the Wild Things Are',
    isbn13: '9780064431781',
    offers: [
      { storeId: 'amazon_de', priceCents: 3986, sellerCertainty: 'direct', seller: 'Amazon', isbn13: '9780064431781', deliveryWindow: null, sameStory: false },
      { storeId: 'libris', priceCents: 7770, sellerCertainty: 'direct', seller: 'Libris', isbn13: '9780064431781', deliveryWindow: null, sameStory: false },
    ],
  },
  {
    id: 'matilda',
    title: 'Matilda (Colour Edition)',
    isbn13: '9780141369365',
    offers: [
      { storeId: 'amazon_de', priceCents: 9433, sellerCertainty: 'direct', seller: 'Amazon', isbn13: '9780141369365', deliveryWindow: null, sameStory: false },
      { storeId: 'libris', priceCents: 8418, sellerCertainty: 'direct', seller: 'Libris', isbn13: '9780141369365', deliveryWindow: null, sameStory: false },
    ],
  },
  {
    id: 'charlie',
    title: 'Charlie and the Chocolate Factory (Colour Edition)',
    isbn13: '9780141369372',
    offers: [
      { storeId: 'amazon_de', priceCents: 9433, sellerCertainty: 'direct', seller: 'Amazon', isbn13: '9780141369372', deliveryWindow: null, sameStory: false },
      { storeId: 'libris', priceCents: 8418, sellerCertainty: 'direct', seller: 'Libris', isbn13: '9780141369372', deliveryWindow: null, sameStory: false },
    ],
  },
];
