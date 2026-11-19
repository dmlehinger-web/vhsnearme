# Contributing

VHS Near Me is generated. Change a data file, run the build, and commit both the data and the HTML it writes. Do not edit `index.html`, files under `cities/`, `mail-in/`, `formats/`, or `about/`, or `404.html` by hand. The next build replaces them.

`css/styles.css`, `templates/page.html`, and `scripts/build.py` are the layout. City pages all use the same layout, so a new city should not need a new template.

## Add a city page

A nightly job can follow these steps without inventing anything else.

1. Pick a slug of lowercase letters, numbers, and hyphens. Example: `austin`. The filename and the `slug` field must match.
2. Copy the template:

   ```bash
   cp data/cities/_template.json data/cities/austin.json
   ```

   Files in `data/cities/` whose names start with `_` are not published. Do not rename `_template.json` itself.

3. Fill `data/cities/austin.json`. Research each business on the web and keep only facts you can point at on that business’s own site (or a listing page they operate). Link that page from `source_url`.

   Required city fields:

   | Field | What to put |
   | --- | --- |
   | `slug` | Same as the filename, without `.json`. |
   | `name` | City name readers use, such as `Austin`. |
   | `state` | Postal abbreviation, such as `TX`. |
   | `state_name` | Full state name. |
   | `areas` | Towns this page is meant to cover. Include suburbs you actually researched. |
   | `meta_title` | The browser title. Name the city. Do not stuff a price you did not verify. |
   | `meta_description` | One or two sentences for search results. |
   | `intro` | A list of paragraphs. Say which nearby towns the page includes, and tell people to call before they drive. |
   | `checked` | The date you read the sources, `YYYY-MM-DD`. |
   | `businesses` | At least one business object. The array order is the order on the page. |

   Required fields on each business:

   | Field | What to put |
   | --- | --- |
   | `id` | Unique slug inside the file, such as `some-shop-austin`. |
   | `name` | The name on their site. |
   | `area` | Neighborhood or city they operate in. |
   | `website` | The page a customer should open. Must be `https://`. `http://` fails the build. |
   | `source_url` | The page you took the facts from. Often the same as `website`. |
   | `source_label` | Short name of that page. |
   | `formats` | Formats their page actually names. Do not add a format they never mention. |
   | `service_mode` | Drop-off, pickup, mail, or whatever they describe, in a few words. |
   | `price_summary` | A short price, or exactly `Call for pricing` when they do not publish one. |
   | `turnaround` | The time they state, or `Not published — call to ask`. |
   | `notes` | A list of sentences. One fact each. You may link with `[words](https://example.com/page)`. No other HTML. |

   Optional fields. Omit the key when you do not have the fact. Do not leave the template’s fake address or phone in place.

   | Field | What to put |
   | --- | --- |
   | `address` | `street`, `locality`, `region`, `postal_code`, only if they publish a street address. |
   | `phone` | The number as printed. |
   | `phone_e164` | Required when `phone` is set. Plus sign and digits only, such as `+15125551212`. |
   | `hours` | Hours copied from their page. |
   | `delivery` | What they say you receive (MP4, DVD, USB, cloud). |
   | `price_lines` | List of `{ "label", "value" }` for a published rate card. |
   | `extra_sources` | List of `{ "label", "url" }` when a price lives on a second page of the same site. |

   Rules the build enforces:

   - The filename must equal `slug`.
   - Placeholder text (`example.com`, `123 Main St`, `YYYY-MM-DD`, `(000) 000-0000`) fails the build.
   - Every business needs a real `source_url`.
   - Do not invent a business, a review, a star rating, or a price. If the number is not on the page, write `Call for pricing`.
   - Arithmetic is allowed only when you show it as arithmetic from a rate they published (for example, their per-minute rate times 120 minutes) and you say that.

4. From the repository root, run:

   ```bash
   python3 scripts/build.py
   ```

   The script rewrites:

   - `cities/<slug>/index.html` — the new city page
   - `cities/index.html` — the cities index
   - `index.html` — the homepage city list
   - `sitemap.xml`
   - `robots.txt`

   It also refreshes the other HTML pages so the header stays in sync. Commit those outputs with the JSON file.

5. Preview under the `/vhsnearme/` prefix (see the README) and open the new city. Check that every price on the page appears on the linked source, and that businesses without a published price say “Call for pricing.”

6. Commit `data/cities/<slug>.json` and the generated files. Do not commit `.env` files. Affiliate IDs, when they exist, go in `data/affiliates.json`, not in a city file.

## Update a mail-in company or a format guide

Mail-in listings live in `data/services.json`. Format guides live in `data/formats/<slug>.json`. Change the file, run `python3 scripts/build.py`, and commit the data plus the regenerated HTML.

Visit links for ScanMyPhotos, Legacybox, and iMemories go through `data/affiliates.json`. Leave `affiliate_id` and `affiliate_param` empty for a normal link. Set both when a network gives you a public publisher ID and the query-parameter name. The build appends that parameter only to the visit link. Source links stay plain. Do not put API secrets in the repo.

## What a city page already includes

You do not copy these into the JSON file. The build adds them on every city page:

- The “how a business gets on this page” note and the “before you go” checklist from `data/snippets.json`.
- A price table, one card per business, source links, and schema.org `ItemList` / `LocalBusiness` data.
- The shared header, footer, canonical URL, and Open Graph tags from `templates/page.html`.
