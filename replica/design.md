# Design system — clipper product (replica-design)

Scope: core loop (upload → AI scoring → editor → export). Clean-room: original palette, type scale, spacing and component names. No branding, colours, copy or assets taken from the reference product.

Stack target: FastAPI + Jinja2 + htmx (server-rendered). Tokens ship as CSS custom properties (`:root`) plus one Jinja2 partial per component under `templates/components/`. No Tailwind dependency; class names use the `c-` prefix (e.g. `c-btn`, `c-card`).

## 1. Colour palette

Accent is a deep teal — chosen to be visually distinct from the reference product's identity. Roles, not brand colours.

| role | hex | used for | validated contrast |
| --- | --- | --- | --- |
| `bg` | #ffffff | page background | — |
| `surface` | #f5f7fa | cards, panels, sidebar | text on surface 16.30:1 (AAA) |
| `surface-2` | #e9edf2 | wells, dropzone idle, timeline track | text on surface-2 14.88:1 (AAA) |
| `border` | #dfe5ec | card/field borders | decorative |
| `border-strong` | #c3ccd6 | dividers, table rules | decorative |
| `border-input` | #6f7b8a | input borders (3:1 UI rule) | 4.31:1 on bg (PASS) |
| `text` | #141a22 | body text | 17.49:1 on bg (AAA) |
| `text-muted` | #5b6673 | secondary text, placeholders | 5.84:1 on bg (AA) |
| `accent` | #0e7a64 | primary actions, links, focus rings | 5.27:1 on bg (AA); white on accent 5.27:1 (AA) |
| `accent-strong` | #0a5f4e | button hover/active | white on accent-strong 7.61:1 (AAA) |
| `accent-soft` | #e2f2ed | selected states, info washes | text on accent-soft 15.12:1 (AAA) |
| `on-accent` | #ffffff | text on accent fills | — |
| `danger` | #c03221 | errors, destructive actions | 5.65:1 on bg (AA) |
| `danger-bg` | #fdecea | error washes | text on danger-bg 15.29:1 (AAA) |
| `success` | #1d7a4c | success text/icons | 5.33:1 on bg (AA) |
| `success-bg` | #e6f4ec | success washes | text on success-bg 15.42:1 (AAA) |
| `warning-text` | #8a5a0b | warning text | 5.39:1 on warning-bg (AA) |
| `warning-bg` | #fdf3e3 | warning washes | — |
| `ink` | #11161d | video player chrome, timeline | on-ink 16.14:1 (AAA) |
| `on-ink` | #eef2f6 | text on dark player | — |
| `on-ink-muted` | #9aa6b2 | secondary text on dark player | 7.33:1 on ink (AAA) |

Virality score tiers (0–100), colour-coded:

| tier | range | bg | text | ratio |
| --- | --- | --- | --- | --- |
| low | 0–39 | `tier-low-bg` #e8ecf1 | `tier-low-text` #5b6673 | 4.93:1 (AA) |
| mid | 40–59 | `tier-mid-bg` #fdf3e3 | `tier-mid-text` #8a5a0b | 5.39:1 (AA) |
| high | 60–79 | `tier-high-bg` #e6f4ec | `tier-high-text` #1d7a4c | 4.70:1 (AA) |
| top | 80–100 | `tier-top-bg` #0e7a64 | `on-accent` #ffffff | 5.27:1 (AA) |

Full contrast report: 26 pairs checked, 0 failing AA (see §8).

## 2. Typography

Open font, same job as the reference category: **Inter** (system-ui fallback). Monospace for timecodes/durations: ui-monospace stack.

| token | size / line-height | weight | use |
| --- | --- | --- | --- |
| `xs` | 12 / 16 | 500 | labels, badges, table headers, caption previews |
| `sm` | 14 / 20 | 400 | body small, inputs, buttons |
| `base` | 16 / 24 | 400 | body, transcript rows |
| `lg` | 20 / 28 | 600 | card titles, dialog titles |
| `xl` | 28 / 34 | 700 | page titles, empty-state headings |
| `display` | 40 / 44 | 700 | marketing hero, score hero numbers |

Buttons and labels use `sm/600`. Never set text below 12px.

## 3. Spacing, radius, shadow, motion

- **Spacing** (4px base): `0, 4, 8, 12, 16, 24, 32, 48, 64`. Component padding snaps to this scale.
- **Radius**: `sm` 6px (inputs, badges), `md` 10px (buttons, cards), `lg` 16px (dialogs, dropzone), `pill` 999px (pills, toggles, avatars).
- **Shadow**: `card` — `0 1px 2px rgba(16,24,40,.06), 0 1px 3px rgba(16,24,40,.10)`; `pop` — `0 12px 32px rgba(16,24,40,.16)` (dialogs, menus, toasts).
- **Motion**: `fast` 120ms, `base` 200ms, ease `cubic-bezier(.2,.8,.2,1)`. Respect `prefers-reduced-motion` (disable transitions).

## 4. Layout

- Max content width 1200px (dashboard, gallery, settings); editor (S09) full-bleed.
- Sidebar 240px, collapsible to 72px icon rail; header 64px.
- Breakpoints: 640 / 1024 / 1440. Below 1024px the sidebar becomes an overlay drawer; the editor stacks preview above transcript.

## 5. Component specs

Naming is original (`c-` prefix). Every spec lists variants, sizes, states, tokens, accessibility, and recon screens.

```
Button (c-btn)
  variants  primary, secondary, ghost, danger, on-dark
  sizes     sm 32px, md 40px, lg 48px; full-width modifier
  states    default, hover (accent-strong), active (translateY 1px), focus-visible (2px accent ring, 2px offset), disabled (opacity .5, no pointer), loading (spinner replaces icon, label kept for SR)
  tokens    primary: bg accent, text on-accent, radius md, font sm/600; secondary: bg surface, border border, text text; ghost: transparent, text accent
  a11y      real <button type>, visible focus, aria-busy + aria-live for loading, min target 40px (44px on touch)
  used on   S01, S04, S05, S06, S08, S09, S10, S11, S12, S13
```

```
TextField (c-field)
  variants  text, textarea, search (leading icon), with-hint, with-error
  sizes     sm 32px, md 40px
  states    default (border border-input), hover (border-strong), focus (2px accent ring), error (border danger + message), disabled (bg surface-2)
  tokens    bg bg, radius sm, font sm/400, label xs/500 text-muted
  a11y      <label> bound by for/id, aria-describedby for hint/error, aria-invalid on error
  used on   S05 (URL input), S06 (keyword, prompt box), S09 (caption edit), S12 (caption text)
```

```
Select (c-select)
  variants  single, multi (checkbox rows), native-fallback
  states    closed, open (pop shadow menu), disabled, error
  tokens    same as TextField; menu bg bg, radius md, shadow pop, max-h 280px scroll
  a11y      button + listbox pattern (aria-expanded, aria-activedescendant), Esc closes, type-ahead
  used on   S06 (genre, language, template), S09 (layout), S10 (aspect ratio), S12 (platform)
```

```
Switch (c-switch)
  variants  default, with-label
  states    on (bg accent), off (bg border-strong), disabled, focus-visible ring
  tokens    track 40x22 pill, knob 18px white, shadow card
  a11y      role=switch, aria-checked, keyboard Space/Enter
  used on   S06 (AI-hook), S10 (watermark, options)
```

```
Slider (c-slider)
  variants  range (min-max), single
  states    default, dragging (enlarged thumb), disabled, focus-visible
  tokens    track 4px surface-2, fill accent, thumb 16px white border accent
  a11y      role=slider with aria-valuemin/max/now/text, arrow-key stepping
  used on   S06 (clip-length range)
```

```
Dialog (c-dialog)
  variants  confirm, form, info
  states    open (overlay rgba(16,24,40,.5), pop shadow), closed
  tokens    bg bg, radius lg, padding 24, max-w 480 (form 640)
  a11y      role=dialog aria-modal, focus trap, Esc closes, return focus to trigger, labelled by title
  used on   S11 (OAuth confirm), S13 (export options), delete confirmations
```

```
Toast (c-toast)
  variants  success, error, info
  states    visible (slide-in 200ms), dismissed (auto 5s, pause on hover)
  tokens    bg ink, text on-ink, radius md, shadow pop; icon coloured per variant
  a11y      role=status (success/info) / role=alert (error), aria-live polite
  used on   all (upload done, render failed, copy link, schedule confirmed)
```

```
SideNav (c-sidenav)
  variants  expanded 240px (icon + label), collapsed 72px (icon rail)
  states    active (accent-soft bg, accent text, 3px left bar), inactive, hover
  tokens    bg surface, font sm/500, item radius md, padding 8/12
  a11y      <nav> landmark, aria-current=page on active, collapsible via button
  used on   S04–S15 (Dashboard, Brand templates, Social accounts, Billing)
```

```
Card (c-card)
  variants  ProjectCard (thumbnail, title, duration, status chip), ClipCard (thumbnail 9:16, title, duration, ViralityBadge, hover actions), StatCard (big number display, delta, sparkline slot)
  states    default, hover (shadow card, translateY -2px), selected (2px accent border)
  tokens    bg bg, border border, radius md, padding 16
  a11y      article/section semantics, whole-card link keeps inner buttons reachable, alt text on thumbnails
  used on   S04 (projects), S08 (clips), S15 (stats)
```

```
ViralityBadge (c-virality)
  variants  tier low / mid / high / top (0–100)
  states    default; tooltip on hover explains the score
  tokens    pill radius, font xs/600, tabular numbers; tier colours per §1 table
  a11y      aria-label "Virality score 82 out of 100, top tier"; never colour-alone (number always shown)
  used on   S08 (clip cards), S09 (editor header)
```

```
Tabs (c-tabs)
  variants  underline, pill
  states    active (accent text + 2px accent underline), inactive (text-muted), hover, focus-visible
  tokens    font sm/600, padding 8/12
  a11y      role=tablist/tab/tabpanel, arrow-key navigation
  used on   S09 (Preview / Transcript), S10 (Style / Layouts)
```

```
ClipTimeline (c-timeline)
  variants  editor (segments + playhead + trim handles), mini (readonly preview bar)
  states    playing, paused, scrubbing (playhead drag), trimming (handle drag), loading (skeleton)
  tokens    track surface-2 on light / #2a3340 on ink; segment accent-soft with accent border; playhead 2px on-accent on ink with knob; trim handles 10px accent pills
  a11y      role=slider labelled "Clip position", arrow keys ±5s, Home/End; time readout in mono, aria-live off while scrubbing
  used on   S09
```

```
TranscriptList (c-transcript)
  variants  default; speaker-labelled rows
  states    default, active-row (accent-soft bg, auto-scroll), selected, edited (amber dot)
  tokens    font base/400, row padding 8/12, radius sm on active
  a11y      list semantics; click-to-seek is a button per row; edits announced via aria-live
  used on   S09
```

```
CaptionBlock (c-caption)
  variants  word, line
  states    default, editing (inline TextField), keyword-highlight (accent-soft bg + accent text), active-word (during preview playback)
  tokens    font sm/500, radius sm
  a11y      contenteditable with role=textbox aria-label, Esc cancels edit
  used on   S09
```

```
CaptionStyleEditor (c-caption-style) — composite for S10
  variants  n/a (panel of controls)
  states    default, disabled-by-plan (template limit reached → upgrade nudge)
  controls  font family Select, font colour swatch, stroke width Slider, shadow Switch, uppercase Switch, emoji Switch, highlight colour swatches, live preview box
  tokens    panel bg surface, radius md, padding 16; preview bg ink with sample caption
  a11y      every control labelled; colour swatches are radio inputs with names, not colour-alone
  used on   S10
```

```
ProgressBar (c-progress)
  variants  determinate, indeterminate
  states    0–100%, failed (danger), done (success flash)
  tokens    track 8px surface-2, fill accent, radius pill; failed fill danger
  a11y      role=progressbar aria-valuenow/min/max/text; failures use role=alert
  used on   S05 (upload), S07 (processing), S13 (export render)
```

```
Dropzone (c-dropzone)
  variants  file, url-paste (with TextField)
  states    idle (dashed border), dragover (accent border + accent-soft bg), uploading (ProgressBar), error (danger border + message)
  tokens    radius lg, padding 48, border 2px dashed border-strong
  a11y      real <input type=file> (visually hidden but focusable), aria-describedby for accepted formats, keyboard operable
  used on   S05
```

```
DateTimePicker (c-datetime)
  variants  date, time, datetime
  states    closed, open (calendar popover), invalid
  tokens    same as TextField; popover shadow pop, radius md
  a11y      native <input type=datetime-local> as baseline, custom grid uses grid pattern with aria-selected
  used on   S12
```

```
AccountMenu (c-account)
  variants  n/a
  states    closed, open (menu pop shadow)
  tokens    avatar 32px pill (initials, accent-soft bg, accent text), menu radius md
  a11y      button aria-haspopup=menu aria-expanded, menu keyboard nav, Esc closes
  used on   S04 (billing, logout)
```

```
Tooltip (c-tooltip)
  variants  n/a
  states    hover/focus visible (200ms delay)
  tokens    bg ink, text on-ink, font xs/500, radius sm, padding 6/8, max-w 240
  a11y      aria-describedby on trigger; not used for essential info alone
  used on   S08 (score explanation), S06 (field hints)
```

```
CreditsPill (c-credits)
  variants  default, low (warning), empty (danger)
  states    default; click → S14 billing
  tokens    pill, bg surface-2, font xs/600, tabular numbers; low uses warning-bg/text, empty danger-bg/text
  a11y      link with aria-label "42 credits remaining, view billing"
  used on   S04 header
```

```
Table (c-table)
  variants  plain, selectable rows
  states    default, hover row, sorted column (aria-sort), empty (EmptyState in body)
  tokens    header xs/600 text-muted uppercase, row font sm/400, dividers border, padding 12/16
  a11y      real <table>, <th scope>, caption or aria-label
  used on   S02 (plan matrix), S12 (queue list)
```

```
EmptyState (c-empty)
  variants  n/a
  states    default; with-action / without-action
  tokens    centred, icon 48px surface-2 pill, title lg/600, body sm text-muted, CTA Button
  a11y      heading + descriptive text; decorative icon aria-hidden
  used on   S04 (no projects), S08 (no clips found), S10 (no templates), S12 (empty queue), S15 (no data)
```

```
Skeleton (c-skeleton) — loading state
  variants  card, row, thumbnail
  states    loading (shimmer, disabled with prefers-reduced-motion)
  tokens    bg surface-2, radius per shape
  a11y      aria-hidden, container has role=status "Loading…"
  used on   S04, S07, S08, S09 loading states
```

```
InlineError (c-error)
  variants  field-error, banner-error, page-error
  states    visible
  tokens    text danger sm/500; banner: danger-bg wash, radius md, padding 12/16, icon
  a11y      role=alert on appearance; field errors linked via aria-describedby
  used on   S03 (auth error), S05 (unsupported source), S07 (processing failed), S11 (token expired)
```

## 6. State patterns (cross-component)

- **Loading**: Skeleton shapes matching the target layout; never a bare spinner for content areas. ProgressBar for determinate work (upload, render).
- **Empty**: EmptyState with one clear next action ("Import your first video").
- **Error**: InlineError near the cause + Toast for global failures; failed renders offer "Retry" and "Notify me by email".
- **Disabled-by-plan**: controls show a lock affordance + upgrade nudge instead of silently hiding (S10 template limit, Pro-gated editor features).

## 7. CSS variable + Jinja2 mapping (stack notes)

`tokens.json` generates `:root` custom properties 1:1 (`--color-accent`, `--space-16`, `--radius-md`, `--font-sans`, `--type-sm-size`, …). Components are Jinja2 partials (`templates/components/c_btn.html` etc.) that reference only variables — never raw hex. htmx swaps re-render partials server-side, so state classes (`.is-loading`, `.is-active`, `[aria-disabled]`) must be set in the partial markup, not via client JS.

## 8. Contrast report

```
python3 ~/workspace/custom-skills/replica-design/contrast.py replica/tokens.json
→ 26 pairs, 0 failing AA (12 AAA, 12 AA, 2 UI PASS)
```

Weakest passing pairs: `accent on surface` 4.91:1, `tier-low-text on tier-low-bg` 4.93:1, `text-muted on surface-2` 4.97:1 — all clear of the 4.5:1 floor. No contrast fixes were required; the first palette passed.

## 9. Next step

`/replica-build` — build screens S01–S15 against these tokens and components, starting with the core loop (S05 → S06 → S07 → S08 → S09 → S13).
