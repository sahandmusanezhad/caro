# The design system — what every page and every panel is drawn with

The plan's phase 5 asks for one design system for the site as it is, the
panels brought into it, and the key routes run in a browser in CI. The
system is not new: the site has drawn with it since the glass of 2026-10-30.
This writes it down, and names what holds each part of it.

## Tokens

Sixteen colours, each a CSS variable in `webapp/web/app/globals.css`, defined
once for the light scheme and once for the dark, and named once more in
`tailwind.config.ts` so that a class can say `text-ink-2` and never a value:

| token | for |
|---|---|
| `--ground`, `--surface`, `--sunk` | the page, a pane on it, a well in a pane |
| `--ink`, `--ink-2`, `--ink-3` | text, quieter text, the quietest that still reads |
| `--line`, `--line-2` | a hairline, a firmer one |
| `--accent`, `--accent-soft` | what you can act on, the one figure a screen is about, the active state |
| `--warn`, `--warn-soft` | a caution |
| `--bad`, `--bad-soft` | a refusal, a fault -- a red darker than the accent, so they part by value |
| `--good`, `--good-soft` | not a green: the strongest contrast on the page, for what is real |

Glass is the same sixteen mixed with transparency: `.glass` and every
`bg-surface` and `bg-sunk` let the page through, and the ground carries four
faint glows of the palette, fainter in the light scheme than the dark. A
browser without `color-mix()` keeps the opaque value written before each
mix; one that asks for less transparency gets the opaque palette back.

## Type, direction, numbers

Vazirmatn, the site's own copy, for everything Persian; IBM Plex Mono for
what is Latin -- an id, a path, a digest -- under `.num`, which also runs it
left to right. A Persian number in a Persian phrase is `.fig`: Vazirmatn's
own tabular figures. `html` is `dir="rtl"`, `lang="fa"`.

## Components

`.panel` (a pane: `.glass`, rounded, padded), `.glass-bar`, `.tiles`,
`.eyebrow` (the line above a heading), `.chip`, `.btn` and `.btn-solid`. A
panel's variants are its border: `border-bad`, `border-warn`, `border-good`
for a state, `border-dashed` for what is not there. The operator's panel
(`/admin`), the seller's (`/login`, `/sell`, `/my-listings`) and the public
pages are drawn with the same classes; a saved car's button is the system's
solid button, not an accent painted onto the plain one.

## The rules, and what holds each

| rule | held by |
|---|---|
| the site and the demo carry one palette, value for value | `tests/test_palette.py` |
| every text colour keeps its contrast band, on glass and on the bare ground, at every glow, in both schemes | `tests/test_palette.py` |
| no component writes a colour of its own -- no hex, no `rgb()`, no Tailwind named colour | `tests/test_palette.py` |
| no font and no stylesheet from another origin | `tests/test_palette.py` |
| no word a page may not say (a sale, a worth, a certainty) | `tests/test_claims.py` |
| nothing that is not a car is drawn as one | `tests/test_screens.py` |
| every key route, at a desk and on a phone, light and dark: right to left, one heading, nothing wider than the screen, nothing asked of another origin, no error; the two schemes two grounds; one panel on every page | `webapp/web/e2e/routes.mjs`, CI's `e2e` job |

A change to the system is a change to `globals.css` and `tailwind.config.ts`
-- and to the demo's copy of the palette in the same commit, which the
palette suite asks for.
