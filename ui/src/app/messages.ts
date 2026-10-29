// RO and EN copy. Feature 8 moves the rest of the app's copy here and adds the
// browser-language default and the toggle. Until then the app runs in 'en'.
// Rules: "order" in EN, "comandă" in RO, never "parcel"/"colet".
// Romanian uses comma-below ș/ț (U+0219/U+021B), never the cedilla forms (U+015F/U+0163).

export type Lang = 'en' | 'ro';

export interface Messages {
  /** {amount} is already formatted as the app formats lei (e.g. 153,50). */
  deliveryGapShort: string;
  deliveryGapReached: string;
}

export const MESSAGES: Record<Lang, Messages> = {
  en: {
    deliveryGapShort: '{amount} lei short of free delivery at {shop}',
    deliveryGapReached: 'Free delivery reached',
  },
  ro: {
    deliveryGapShort: 'Mai ai {amount} lei până la livrarea gratuită la {shop}',
    deliveryGapReached: 'Comanda are livrare gratuită',
  },
};

export function fill(template: string, values: Record<string, string>): string {
  return template.replace(/\{(\w+)\}/g, (whole, key: string) => (key in values ? values[key] : whole));
}
