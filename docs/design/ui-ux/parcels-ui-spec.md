# Parcels UI: build spec (Prism, 2026-10-29)

Hand-off to `ui/`. Look: `docs/design/ui-ux/*.dc.html` and `omni.css`. Payload: `POST /solve` at `6a61590`.
This file says what each screen is made of, which `/solve` field feeds each number, and how to reach it on the real basket.

## Rules for every screen

- **The view computes nothing.** Money is integer cents from a field, shown `515,16 lei` (comma decimal). `null` is never shown as 0: it is the solid orange tag `not printed`.
- **Not ranked** (any `not_ranked[]` entry, any shop with `status: not_ranked`): show `books_subtotal_cents` and the tag `delivery not printed`. Never a total. The real-basket example: `cheapest.not_ranked[0].books_subtotal_cents` = 484,36 (Amazon.de alternative).
- **Counts** are `.length` of a returned list, or `order_count`. Words (`2 parcels`) use `cheapest.order_count`, never a literal 2.
- **Dates.** `read_at` is a date (`2026-10-28`), not a time. The stamp reads `prices read 28 Oct` or `27–28 Oct` from `read_at_range`. The canvas `09:40` is not in the payload and is not shown.
- **Links.** `Open on {shop} ↗` goes to `listing_url`, `target=_blank rel=noopener`. No `listing_url` hides the control; it never falls back to a homepage.
- **System.** Bricolage Grotesque display, Inter text, white ground. Kraft #f4efe6 only on parcels. Green #14532d only for the chosen answer. Radii: 24 parcels and boxes, 16 fields, pills 999. Controls >= 44 px high (chips too: 44, not the canvas 32, so parcels are taller on phone). Borders solid only.
- **Widths.** 390 phone (one column, 16 px gutters), 834 tablet (32 px gutters, one column of parcels), 1440 desktop (1200 max, `main` + `rail` split, parcels in two columns). No horizontal scroll at 390.
- **Order on phone.** Headline first, then parcels, then the shops-left-out panel. On 1440 the 03 headline moves to the right rail (DOM order stays headline first).
- **Routes** (hash, so every screen has a URL): `#/` 01 · `#/add` 02 · `#/result/cheapest` 03 · `#/result/one` 04 · `#/result/custom` 05 · `#/parcel/{store_id}` 06 · `#/book/{item_id}` 07 · `#/editions` 08 · `#/shop/{store_id}` 09 or 10 (by `shops[].not_selectable_code`). 11 and 12 are the result screens when `degraded.kind` is `one_book` or `one_shop`.
- **Query.** `?fixture=failed-read` loads `/fixtures/failed-read.json` as the payload (static, no re-solve). `?books=a,b` starts with those basket ids.

## Data flow

1. Load: `POST /solve {}` (cache path, real basket). Keep it as the **snapshot**: the catalogue for entry, search and basket (`books`, `shops`).
2. Basket = all `books[].item_id` minus removed ones. Full basket: `POST /solve {selected_store_ids?, edition_pins?}`. Smaller basket: `POST /solve {source:"given", stores, items, ...}`, with `stores` and `items` rebuilt only from snapshot fields (`shops[]` fees, `books[].shops[]` offers incl. `edition`, `listing_url`, `read_at`). Offers at `priced: false` shops are left out (the API cannot take them).
3. Custom: `selected_store_ids` from the switches. Editions: `edition_pins` from the sheet, sent as a **preview** while it is open; `Apply` keeps it, `Cancel` drops it.
4. Fixture mode: no re-solve; edits show a note.

**Missing fields** (ask Hermes; not computed in the view): `author` per book (copy shows ISBN only) · delivery window / "arrives" (row dropped) · the € price on the page and the rate (rows dropped; prices are lei as returned) · a title/ISBN search endpoint (the field searches the basket's `books` only; no match says "Not in the shops we read") · eMAG offers do not survive a re-solve of a smaller basket (the `given` path drops unpriced shops) · `read_at` is a date, not a time · the "Bookzone kept under 200" note (a solver rule, not a field; dropped).

---

## 01 Entry
Structure: header (brand left · two 44×44 icon buttons right: globe for language menu, sun/moon for theme menu) · h1 "One parcel, or the cheapest?" · subtitle · field label `Book title or ISBN` · input (52 px, r16) · `Find book` primary button · `Photo of a list` secondary button with camera icon · box "How it works" (3 steps) · generic footnote ("We read and index shop data from a few sources. Where a shop does not publish a fee, we leave it blank rather than guess.").
Header menus: `.iconbtn` triggers open `.icmenu` with `role="menu"` and `aria-haspopup="menu"`. Language menu: English / Română, current item has `aria-current="true"` and checkmark. Theme menu: System / Light / Dark, same pattern. Menus open on click/Enter/Space/ArrowDown, close on Escape/outside click/item select, focus returns to trigger on close. Keyboard navigation: ArrowUp/Down cycle within menu, Home/End go to first/last.
Dense layout: field top 184/220/249 at 390/834/1440. No segmented footer on entry (settings moved to header menus).
Fields: step 2 text is generic ("We read each shop's prices, postage and free-delivery thresholds."), not naming specific shops. Footnote is generic, not naming shops.
States: loading (field enabled, footnote visible) · load error ("We couldn't load the shops.", `Try again`).
390: stacked. 834: h1 48 px, content 640 max. 1440: stacked, content 720 max.
Reach: `#/`.
Pick list: unchecked shops shown as compact chip row per book (`.not-checked` with `.not-checked-chip`), not repeated paragraphs. No-offer state: shows "No shop lists this ISBN." with next-step links (Try another edition → editions overlay, Search this shop → first shop's search URL if available).

## 02 Adding books
Header with `{basket.length} books` · field (same label as 01) · result card · basket chips · `See parcels` (disabled with an empty basket).
Card: cover slot (placeholder icon), `books[].title`, `ISBN {isbn13}` or tag `ISBN not printed`, `{editions.length} editions`; edition chips `Any` + `books[].editions[].edition`; "First found at {shop} · {price}" = first `books[].shops[]` with a price (`store_id`, `price_cents`); `View on {shop} ↗` = its `listing_url`; `Add to basket` / `Remove from basket`.
States: empty field (no card) · match · no match · empty basket.
Basket chips open 07. Reach: type `wild` or an ISBN from `books[].isbn13`.

## 03 Result: n parcels, cheapest
Header: brand · `{basket.length} books · Edit` (to 02). The stamp from `read_at_range` sits in the pills row beside `Editions` (not in the header: at 390 it made the header two lines).
Pills: `Editions: any` or `Editions: {n} pinned` (n = keys of `edition.pins`) → 08.
Tabs: `1 parcel` + `+{one_parcel.answer.delta_vs_cheapest_cents}` · `{cheapest.order_count} parcels` + "cheapest" · `Custom` + "choose stores". Only the selected tab's number is headline-sized (`.big`, green).
Headline `cheapest.total_cents` lei · "Delivery included · one parcel costs {delta} more".
One parcel per `cheapest.orders[]` (kraft, green border): `{shop} · {books.length} books ›` → 06; right `order_total_cents`; book chips (`books[].title`) → 07; meter and line "Free delivery from {free_delivery_threshold_cents} ✓ · {over_under_threshold_cents} over" when `threshold_crossed`, else "{short_of_threshold_cents} short of free delivery"; `delivery_cents` when `delivery_known`, else tag `delivery not printed`.
Grey panel "Shops left out": every `shops[]` with `selectable: false`: name, `not_selectable_reason`, → 09 / 10.
Not ranked: each `cheapest.not_ranked[]` as a grey box "Another split: {shop} {n} + …", `books_subtotal_cents`, tag `delivery not printed` (`missing_fees[].store_id` named). No total.
States: `cheapest.status` `not_ranked` or `not_possible` (reason, no total).
Reach: `#/result/cheapest` on the real basket (515,16; Amazon.de 4 + Libris 3; eMAG left out; alternative 484,36).

## 04 Result: 1 parcel
Same header, pills, tabs (1 parcel selected). Headline `one_parcel.answer.total_cents`, ink (`.big.alt`) because it is not the cheapest · "All {n} from {best_store_id} · {delta_vs_cheapest_cents} more than the cheapest". **No bottom buttons.** Parcel = `answer.orders[0]` as 03 with an `Open on {shop} ↗` per book.
"Where the {delta} comes from": rows of `one_parcel.per_book_delta[]` with `delta_cents` not 0: title, `cheapest_price_cents` → `price_cents`, signed `delta_cents` (`+` costs more here, `−` is cheaper here; the real basket has both, and only the full list adds up to the headline delta).
Other shops: `one_parcel.shops[]` not the best: `not_possible` → `reasons[].text`; `not_ranked` → `books_subtotal_cents` + tag `delivery not printed`.
States: `one_parcel.status` `not_possible` (reason, no total).
Reach: `#/result/one` (Libris 558,73, +43,57).

## 05 Result: custom, choose stores
One switch per `shops[]` (44 px row, 48x28 toggle). On = chosen. Disabled with `not_selectable_reason` when `selectable: false`. Sub-label: chosen `{orders[].books.length} books · {order_total_cents}`; off "Off", plus "· {n} books moved" only when `custom.moves[]` has entries from this shop.
Headline `custom.total_cents` lei · "{custom.order_count} parcels · {delta_vs_cheapest_cents} more than the cheapest" (0 reads "same as the cheapest"). Parcels = `custom.orders[]` as 03; moved-in books carry a `moved` tag (`custom.moves[].item_id`). "Moved": `moves[]` title, `from_store_id` → `to_store_id`, `to_price_cents`.
Blocked: `custom.status` `not_possible` → `custom.reason`, `custom.unselectable[]`, **no total**. The last chosen shop cannot be switched off.
Reach: `#/result/custom`; Amazon.de + Libris + Bookzone returns 530,45 with Ghici at Bookzone.

## 06 Parcel detail
Header `‹ Parcels` + stamp `orders[].read_at`. h2 "Inside the {shop} parcel". Per `books[]`: title (→ 07), `edition` (null → tag `edition not printed`), `price_cents`, `Open ↗` (`listing_url`). Free-delivery card: `free_delivery_threshold_cents`, meter, `over_under_threshold_cents`. Totals: `books_subtotal_cents`, `delivery_cents` (null → tag), `order_fee_cents` (null → tag), `Parcel total` = `order_total_cents` (null → "no total"). Data: the `orders[]` of the tab you came from.
Reach: `#/parcel/amazon_de`.

## 07 Book detail
Header `‹ back` + stamp. Cover slot, h2 title, `ISBN {isbn13}` or `ISBN not printed`. Green box "In your cheapest plan · {assigned_store_id}" with that shop's `price_cents` and `Open on {shop} ↗`. "Other shops for this book": `books[].shops[]`: status text (in plan · compared · fees not printed · not listed · out of stock · couldn't read · other edition), `price_cents` or "—", `↗` when `listing_url`.
Foot: "Book prices only. What you pay for postage depends on the whole parcel."

## 08 Exact edition (sheet at 390, modal at 834 and 1440)
h2 Editions, `Cancel`. A row per book, chips `Any` + `books[].editions[].edition`. Green **preview** box: `edition.total_cents`, `{cheapest.order_count} parcels`, `edition.delta_cents` ("same total" at 0) against `edition.unpinned_total_cents`. Each `edition.not_ranked[]`: grey "Another split can't be priced", `books_subtotal_cents`, tag `delivery not printed`. `edition.status` `not_possible` → `edition.reason`, no total, `Apply` disabled.
Reach (real basket): pin Ghici to `board_book` → 515,16, same total, Amazon.de alternative 484,36 not ranked. Pin Wild Things to `hardcover` → `not_possible` reason. A pin that changes the price needs a multi-edition basket (not in the real data): see Fixtures.

## 09 Store excluded (eMAG)
Header `‹ Parcels` + stamp `shops[].read_at`. h2 "{shop}: checked, can't be priced". Copy from `not_selectable_reason`. Rows: delivery, order fee = tag `not printed`; `Parcel total: no total`. Book rows: `books[].shops[]` with this `store_id` and a price (title, price, ↗).
Reach: `#/shop/emag`.

## 10 Failed read
Header `‹ Parcels` + stamp `failed_reads[].failed_at`. h2 "We couldn't read {shop}"; "tried {attempts} times at {failed_at}"; "It isn't part of your parcels. The {cheapest.total_cents} covers the shops we could read." `Try again` re-runs the solve. No site link (no `listing_url` exists for a never-read shop). Stamps per shop: `shops[].read_at`.
Reach: **fixture only.** Cărturești is not in `data/baskets/ro-v1.yaml`. `ui/public/fixtures/failed-read.json` is recorded by `scripts/record_failed_read_fixture.py` from the real solver and plan code, plus one shop with 3 failed tries on every book. Open `?fixture=failed-read#/shop/carturesti`.

## 11 One book
`degraded.kind = one_book`. Header `1 book · Edit`. h2 "One book, one parcel. Which shop?" + link to 07. List `one_parcel.shops[]`: ranked = parcel (green on the best) with `total_cents`, `books_subtotal_cents`, `Open on {shop} ↗` for the best; `not_ranked` = grey box with `books_subtotal_cents` and tag `delivery not printed`; `not_possible` = `reasons[].text`. Tabs hidden.
Reach: remove six books on 02, or `?books=wild`. Real data via a `given` re-solve.

## 12 Only one shop
`degraded.kind = one_shop`. Tabs: `1 parcel` "only way" · `parcels` "not possible" (`cheapest.reason`) · `Custom` "no other shop" (both disabled). Headline `one_parcel.answer.total_cents`, "Only {degraded.store_id} lists all of them". Parcel = `answer.orders[0]`. Box "Why not 2 parcels?": other `one_parcel.shops[]` with `reasons[].text`.
Reach: `?books=vhc,owl` (only Libris lists both). Real data via a `given` re-solve.

## Fixtures

| Screen | Fixture? | How |
|---|---|---|
| 10 failed read | yes | `ui/public/fixtures/failed-read.json`, from `scripts/record_failed_read_fixture.py` |
| 08 with a price change | no for the screen | real books have one edition each, so `delta_cents` is 0; a multi-edition `given` basket would show a change |
| all others | no | real basket or a `given` re-solve from snapshot fields |
