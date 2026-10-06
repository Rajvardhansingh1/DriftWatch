# DriftWatch landing: design direction

## Direction

A bench instrument for LLM output: grey enamel in light mode, the existing dashboard's dark panel in dark mode, and one amber that means "drift" and nothing else, so the page reads like the readout it sells rather than an advert for it.

Why this and not the obvious options:

- The product already has a colour language. In `/demo`, amber `#F2B84B` marks drift, red marks alerts, green marks stable. The landing page keeps amber for drift only. A visitor who later opens the dashboard sees the same colour mean the same thing.
- Light mode is a cool grey, not cream or white. Cream with a warm accent is the default look of generated pages right now, and pure white makes the amber look like a warning label. Cool grey is the colour of lab hardware and keeps the amber legible as a signal.
- Dark mode reuses the dashboard's `#0a0e14` base and `#10151d` panel, so the two surfaces feel like one product.
- Green is left out of the landing page. Stable is shown as neutral grey points. The page is about the moment something moves, and a third hue would dilute that.

## Palette

Seven tokens, defined on `.mk-root` in `marketing.css`. Contrast is WCAG 2.x relative luminance, computed for every pairing that carries text. Body text and muted text clear 4.5:1 on both `bg` and `surface` in both themes.

| Token | Light | Dark | Role |
|---|---|---|---|
| `--mk-bg` | `#e9ecee` | `#0a0e14` | Page ground |
| `--mk-surface` | `#f7f8f9` | `#10151d` | Cards, code blocks, the tilt panels |
| `--mk-fg` | `#11171e` | `#e6edf3` | Body and headings |
| `--mk-muted` | `#4b5562` | `#8a97a6` | Secondary text, captions, axis values |
| `--mk-line` | `#c5ccd3` | `#1e2733` | Hairlines and card borders (decorative, not text) |
| `--mk-accent` | `#8a5300` | `#f2b84b` | Drift: drifted points, links, focus ring, the one primary button |
| `--mk-warn` | `#b3261e` | `#ff6b6b` | Alerts and form errors only |

Measured ratios (text colour on ground):

| Pairing | Light on bg | Light on surface | Dark on bg | Dark on surface |
|---|---|---|---|---|
| fg | 15.19:1 | 16.95:1 | 16.37:1 | 15.49:1 |
| muted | 6.38:1 | 7.12:1 | 6.50:1 | 6.15:1 |
| accent | 5.33:1 | 5.95:1 | 10.81:1 | 10.23:1 |
| warn | 5.51:1 | 6.15:1 | 6.97:1 | 6.60:1 |
| line (non-text) | 1.37:1 | 1.52:1 | 1.28:1 | 1.21:1 |

`line` is only for borders beside content that is already legible; never use it for text or for the only edge of a control.

The light accent is a dark amber so it passes as link text. Primary buttons use `--mk-accent` as the fill with `--mk-surface` as the label (5.95:1 light, 10.23:1 dark).

Static images (`hero-fallback.svg`, `og.png`) cannot read CSS variables, so they use fixed mid-tones that work on both grounds: neutral points `#7d8794` and drifted points `#d4901f` with a `#8a5300` outline.

## Type

IBM Plex only, as loaded in `app/layout.tsx` (weights 400, 500, 600). No third family.

| Use | Family | Size / line height | Weight | Tracking |
|---|---|---|---|---|
| Hero headline | Plex Sans | `clamp(40px, 5.2vw, 64px)` / 1.05 | 600 | -0.02em |
| Section heading | Plex Sans | 30px / 1.2 | 500 | -0.01em |
| Sub heading | Plex Sans | 22px / 1.3 | 500 | 0 |
| Body | Plex Sans | 17px / 1.6 | 400 | 0 |
| Caption, secondary | Plex Sans | 15px / 1.5 | 400 | 0 |
| Code, numbers, API names | Plex Mono | 14px / 1.55 | 400, 500 for emphasis | 0 |

Scale steps by roughly a perfect fourth (15, 17, 22, 30, 40 to 64). Body measure stays under 68 characters (`max-width: 38rem`). Numbers use `font-variant-numeric: tabular-nums`.

Mono is for things a user would type or read off a meter: an endpoint, a score, a threshold. It is never a decorative label. Headlines are sentence case, one colour, no single highlighted word.

## Layout

- 12-column grid, 24px gutters, max content width 1180px, 24px side padding below 768px.
- Hero is left-aligned. Text sits in columns 1 to 5. The WebGL point cloud (Task 14) fills columns 6 to 12 and bleeds past the right edge of the container to the viewport edge. That bleed is the deliberate asymmetry: the instrument is bigger than the frame, the words are not.
- Below the hero, each section uses a left rail (columns 1 to 3) for the section heading and a content column (4 to 11). Column 12 stays empty. The empty column keeps line length honest and stops the page from feeling like a centred brochure.
- Cards appear only where the content is an object you could inspect: a signal panel, a code sample, a sample alert. No grid of identical feature cards. Card radius is 4px; buttons and inputs are 2px; hairline dividers are square.
- Depth comes from `.mk-tilt`: a small perspective tilt and a cast shadow on hover in light mode, a deeper shadow plus a faint top highlight in dark mode, where plain shadows disappear.
- Mobile: hero stacks text first, then the cloud at a 1:1 box. The left rail collapses above its content.

## Motion

What moves, in order of importance:

1. The hero point cloud rotates slowly. Over a few seconds a subset of points leaves the cluster and turns amber. This is the one orchestrated moment on the page and it shows the product's idea without words.
2. `.mk-tilt` cards tilt toward the pointer on hover, 240ms ease-out.
3. `.mk-skeleton` shimmers while live data loads.

No scroll-triggered fade-ins, no parallax, no animated counters.

Under `prefers-reduced-motion: reduce` everything stops: the skeleton gets `animation: none`, tilt loses its transition and transform, and the hero swaps the WebGL scene for `public/hero-fallback.svg`, a still frame of the same cloud.

## Refusals

1. No purple-blue gradient blobs, glows or mesh backgrounds.
2. No emoji and no generic icon grids. If an icon is needed it explains a control, not a feature list.
3. No centred-everything hero. Text is left-aligned against the grid.
4. No fake logos, testimonials, customer counts or stats. Any number on the page comes from the product or is labelled as an example.
5. No em dashes in copy. Use a full stop or a comma.
6. No all-caps eyebrow labels above headings, and no numbered markers unless the content is a real sequence (setup steps are; features are not).
7. No cream background with a terracotta accent, and no neon green "run" button: both are defaults, not choices for this product.
8. No glassmorphism. Surfaces are opaque, like an instrument panel.
