# Omnibasket: UI / UX (the go-to design)

Chosen by Adrian on 2026-10-29: direction B, "Parcels", with his changes. This replaces the earlier three-directions exploration.

The `.dc.html` files are canvas source. They load the canvas runtime (`support.js`) and the shared stylesheet from the canvas's asset store, so they don't render on their own. `omni.css` is a local copy of that stylesheet. On the canvas, press Play on any screen or open a size's flow map (`M00`, `T00`, `D00`) to walk the flow.

## Files

| Prefix | Size |
|---|---|
| `M00`–`M12` | Mobile, 390 × 844 |
| `T00`–`T12` | Tablet, 834 × 1194 |
| `D00`–`D12` | Desktop, 1440, fluid |
| `Main.dc.html` | Overview, what changed, system |

The screens are the same at every size: 00 flow map · 01 entry · 02 adding books · 03 result: 2 parcels, cheapest · 04 result: 1 parcel · 05 result: custom, choose stores · 06 parcel detail · 07 book detail · 08 exact edition · 09 store excluded (eMAG) · 10 failed read (Cărturești) · 11 one book · 12 only one shop.

## Decisions baked in
- The result has three tabs: 1 parcel / 2 parcels, cheapest / Custom, choose stores. The 1-parcel tab has no bottom buttons, and there is no Finalize or summary step.
- Custom: each shop has an on/off switch. The switched-on shops are the ones the shopper orders from, and each gets at least one book. Books from switched-off shops move to the switched-on ones, the cheapest way. If a switched-on shop can't take any book, the screen says why and gives no total.
- Every book opens a book detail screen with a button to that shop's listing. Parcel rows have an "Open ↗" button on each book, so shoppers fill each cart themselves.
- Borders are solid everywhere. Unknowns are a solid orange "not printed" tag, never a number.
- Bookzone's delivery at 200 lei and above is treated as not printed, so the custom split keeps Bookzone under 200.

## About the numbers
Real launch data: 515,16 · 558,73 (+43,57) · 530,45 (+15,29) · Amazon.de free from 262,19 · Bookzone 10,90 + 1,99 under 200 · eMAG excluded for unknown fees.

Illustrative, built to add up exactly to those totals: the per-book prices, the € rate (4,9938), Libris's delivery terms, eMAG's book prices, the 520,94 edition case, and the 1-book and one-shop baskets. ISBNs and covers are placeholders. Shop links point to each shop's homepage.
