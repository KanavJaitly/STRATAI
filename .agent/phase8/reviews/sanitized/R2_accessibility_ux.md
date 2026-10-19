> **SANITIZED DERIVATIVE, NOT THE VERBATIM ORIGINAL.** This was made on 2026-10-19 from the local evidence
> file `.agent/phase8/reviews/R2_accessibility_ux.md` (git blob `95e2c60d31ddb99d8274b45ada6fafaa37609cb7`). The original stays local as evidence and is
> excluded from the commit candidate; this derivative is the copy proposed for the commit. Only one thing changed: 2 local scratchpad path(s), which contained the machine's username
> and session id, were replaced with `<local-scratchpad>`. Every finding, verdict and other word is
> unchanged.

# Phase 8 independent review — accessibility and UX

An independent subagent review (fresh context, read-only brief) of the uncommitted `phase8/build` working tree, returned 2026-10-19T03:39:11.247Z (UTC). Recorded verbatim from its final report. What was done about each finding: `REVIEW_DISPOSITION.md`.

---

Phase 8 accessibility and UX review. I edited no files and made no commits.
  
  **Read this first.** Someone edited `frontend/src/dashboard/display.tsx` at 23:37, while I was reviewing. The badge now shows the raw `validation.status`. Because of that, `npx vitest run` gives 5 failures out of 96 tests: 4 in `display.test.tsx` and 1 in `AlliancePage.test.tsx`, which can no longer find the text "approximately calibrated qualification". Either the edit or the tests need to change. `npx tsc -b` passes. Line numbers below for `display.tsx` may have moved by a few lines.
  
  ## Confirmed findings
  
  **High**
  
  1. **No focus management or page title on navigation.** `App.tsx:369` makes `<main id="main" tabIndex={-1}>` focusable, but nothing moves focus there when the route changes. Nothing sets `document.title` either: every page is titled "STRATAI" (`index.html:7`). After a client-side navigation, screen-reader users stay at the old link with no announcement. This fails WCAG 2.4.2 and the intent of 2.4.3.
     - Fix: in `Shell`, add a `useEffect` on `location.pathname` that sets `document.title` (for example "Team 11 · 2026mrcmp · StratAI") and focuses `#main` or the `h1`.
  
  2. **The validation explanation exists only in a `title` tooltip** (`display.tsx` around line 22). Keyboard, touch and most screen-reader users cannot reach it. The visible text is the raw label: "descriptive definition pending", "approximately_calibrated_qualification" and so on. This is the main way the dashboard says what a number means, and it currently fails 1.3.1 and 3.3.2 intent.
     - Fix: render the explanation visibly, or as a `<details>`, or as a focusable toggle. At minimum, add visually-hidden text or `aria-describedby` that points to it.
  
  3. **Closed `<details>` are not expanded when the report is printed** (`dashboard.css:155`). `.report details { display:block }` does not open a closed `<details>`; its contents stay hidden. So the "Evidence per robot" section prints only the six summary lines.
     - Fix: set `open` on `beforeprint` and restore it on `afterprint`. Or render that evidence without `<details>` in a print-only block.
  
  **Medium**
  
  4. **Input, select and textarea borders are too faint.** The `--border` token has 1.35:1 contrast against the surface in light mode and 1.36:1 in dark (`index.css:6`, `index.css:24`, used at `:75`). The border is the only visible edge of a field, and 1.4.11 asks for 3:1.
     - Fix: add a `--input-border` token, for example `#8a94a3` in light and `#5d6878` in dark.
  
  5. **Breadcrumb links look like plain text.** The main-nav rule `nav a { padding:6px 12px; text-decoration:none; color:var(--text) }` (`index.css:56`) also applies to `<nav class="crumbs">` (`common.tsx:16`). In the screenshots the crumbs ("2026 events › 2026mrcmp") are indented, black and not underlined. This fails 1.4.1 for link identification.
     - Fix: scope the rule to `nav[aria-label=Main] a`, or give `.crumbs a` its own style with the accent colour and an underline.
  
  6. **Async results appear in live regions that are created at the same moment as their content.** Examples:
     - `PickListView` uses `aria-live` on a div that mounts together with its result (`AlliancePage.tsx:165`).
     - `ComparisonResult` does the same (`strategy.tsx:~215`).
     - The loading text is a `role=status` paragraph that is inserted already filled (`display.tsx` `ResourceView`).
     - The save result is a `role=status` paragraph inserted with its text (`coachInputs.tsx:~37` and `~91`).
  
     Screen readers often skip regions like these. Also, the submit buttons become `disabled` while busy (`AlliancePage.tsx:155`, `strategy.tsx` "Evaluate side by side", `coachInputs.tsx`), which drops keyboard focus to `<body>`.
     - Fix: keep one live region per section always mounted and update its text. Use `aria-disabled` and ignore clicks, rather than `disabled`, while busy.
  
  7. **Chart text becomes unreadable at 390 px** (`charts.tsx`, `dashboard.css:123`). Tick and axis labels are `font-size:11px` inside a 640-unit viewBox, so they shrink to about 6 px on a phone (see `review_m_team.png`). The data table is collapsed by default.
     - Fix: give the chart a minimum width with horizontal scroll, or scale the font with the viewBox. Or open the data table by default on narrow screens.
  
  8. **Wrong heading order in the report.** `StrengthView compact` renders an `h2` "Team N", with `h3` beneath it, inside each `<details>` under the `h2` "Evidence per robot" (`ReportPage.tsx:~200`, `TeamPage.tsx:68`). On the report page, `NotProducedItem` uses `h4` directly after the Synergy `h3`, as if those items belonged to Synergy (`ReportPage.tsx:~67`).
     - Fix: pass a heading level into `StrengthView` (h3 inside the report). Group the not-produced items under their own `h3`, or make them `h3`.
  
  9. **Raw machine codes are shown as the user-facing explanation.** Examples:
     - "— no_prior_concluded_event_epa" repeated in every EPA cell
     - "Source — · withheld_no_prior_event", with a stray leading dot (`TeamPage.tsx:78`)
     - "— model_not_loaded" in every Role cell of the report
     - "insufficient_data: fewer than 2…"
  
     The refusal notice also says "model of record … (the environment of record)", which is jargon to coaches and scouts. Together these make the many "unavailable" states hard to understand.
     - Fix: map codes to plain text through `refusals.ts` and `labels.ts`, keep the code in small print, and say an absence once per section rather than once per cell.
  
  10. **Tables clip and give no cue at 390 px.** `table.grid` switches to `display:block; overflow-x:auto` below 720 px (`index.css:95-96`). The report's alliance tables cut off at "no_prior_concluded_event_e"; the event's Matches table and the Defense/Feeding table also clip. At 1280 px the Alliance candidates table already cuts off the Synergy and Role-compatibility columns (`td` uses `nowrap`, `dashboard.css:94`). Setting `display:block` on a `<table>` can also remove its table semantics in some engines, notably WebKit.
     - Fix: keep `display:table` inside the existing `.table-scroll` wrapper, and add a visible scroll cue or a sticky first column. Let long codes wrap with `overflow-wrap:anywhere`.
     - The same 720 px breakpoint probably applies when printing on A4, where the printable width is about 717 px, so report tables may clip on paper. I could not confirm this because no PDF renderer is available.
  
  11. **Tab keyboard behaviour has three problems** (`common.tsx:29-56`, `useTab.ts:10`):
      - Every arrow-key press pushes a browser history entry, because `setParams` is called without `{replace:true}`, so Back steps through tabs one at a time.
      - Because tabs activate automatically, an arrow press immediately fetches that tab's data; "Rankings" can take several seconds.
      - `aria-controls` on inactive tabs points to panels that are not rendered.
      - Fix: use `replace:true` for tab changes, and render inactive panels `hidden`, or drop `aria-controls` on inactive tabs.
  
  **Low**
  
  12. **The page header takes about 300 px on a 390 px screen** before the `h1`: the wrapped nav plus the name and token fields (`App.tsx:22-53`, see `review_m_event.png`). The tab strip also clips "Qualification forecast" with no overflow cue (`dashboard.css:53`).
      - Fix: collapse the session bar behind a disclosure on narrow screens, and fade the tab strip's edge to show it scrolls.
  
  13. **The main nav marks no item active on event, team, match or report pages.** "Events" uses `end` (`App.tsx:359`), so it only matches `/`. Also, `NavLink` active state relies on colour alone, without `aria-current` being styled distinctly. It is set by default, so this is fine for assistive technology.
      - Fix: drop `end`, or match `/events`, `/matches` and `/report` as well.
  
  14. **Link and control names repeat.** Each row has a "Report" link (`EventPage.tsx:330`); give them `aria-label={`Pre-match report, ${matchLabel(m)}`}`. The strategy editor has checkboxes named only "auto", "teleop" and "endgame", three times each (`strategy.tsx`), though they sit inside a named group. The report's radio buttons are named only "Red" and "Blue" (`ReportPage.tsx:462`).
  
  15. **The Liveness badge is always green whatever the status** (`StatusPage.tsx:12`).
      - Fix: choose the tone from `h.status` (`ok` versus anything else).
  
  16. **The alliance configuration warning is a bare `span` with the `notice-warn` class and no role** (`AlliancePage.tsx:63`), so it is never announced. In Strategy lab, "Evaluate pairing" is disabled with no explanation until a team is picked (`StrategyLabPage.tsx:334`).
      - Fix: give the warning `role=status`, and always show "Choose six different teams" next to the disabled button.
  
  17. **Event page "Moment" control.** It sits above all tabs but the Teams tab ignores it (`EventPage.tsx:161`), which may confuse users. Hide it on the Teams tab, or add a note there.
  
  18. **Possible empty coach editor on the match page.** In one screenshot (`review_match.png`), the "Coach strategy for red" editor and the "Save" table were empty while the alliance line showed three teams. A fresh DOM dump showed the editor filled correctly. Treat it as a possible render race in the `StrategyWorkbench` key/reset logic (`MatchPage.tsx:261`, `strategy.tsx` reset during render); it is not confirmed.
  
  ## Contrast (computed, both themes)
  
  Every text pair passes AA, at 4.92:1 or better:
  - text and muted text on the background, surface, info, selected, old, ok, warn and bad backgrounds
  - every badge's foreground on its background
  - the accent colour on the surface and the selected background, and the accent-text colour on the accent
  - the red and blue alliance colours on their own backgrounds, on the surface and on the selected background
  
  For non-text elements:
  - The focus ring (`--focus`) is 5.68:1 or better against the background and surface. It is 1.0:1 against the accent colour, but `outline-offset:2px` keeps it off accent-filled buttons, so this is OK.
  - The neutral chart colour against the surface is 5.4:1 in light and 6.9:1 in dark.
  - `--border` fails, at 1.26–1.50:1 (see finding 4).
  
  ## What passes
  
  - The overall structure is sound:
    - a skip link
    - `header`, a labelled main `nav`, `main` and a breadcrumb `nav`
    - one `h1` per page, with `section` elements labelled by their `h2`
  - Controls are labelled with a wrapping `<label>`, and the session fields and strategy-editor selects have `aria-label`s that name the team.
  - The tabs are a correct ARIA tablist with roving tabindex and Left/Right/Home/End keys.
  - `:focus-visible` gives a 3 px outline, and the loading spinner respects `prefers-reduced-motion`.
  - Colour is never the only signal: alliances carry "RED"/"BLUE" text, scores have a "(blue won)" note, and badges carry text.
  - Charts use `role="img"` with a summary `aria-label`, a `<title>` on each bar, a data table with `th scope`, and missing points listed rather than drawn as zero.
  - Data tables have visually-hidden captions plus `th scope="col"` and `scope="row"`. The one exception is the Defense/Feeding table in `TeamPage.tsx:96`, which has no caption.
  - An absent value is shown as a dash plus "not available" for screen readers, plus the reason, and never as 0.
  - Refusals use `role=alert` for failures and `role=status` for the rest, keep the code and request id visible, and offer a Retry button for failures.
  - Empty states are clear ("No event matches…", "No matches for this team at this moment."). Each unavailable model appears as its own notice and does not blank the page.
  - The print stylesheet hides the chrome and the share/as-of controls, and keeps badges and chips readable in black on white.
  
  Screenshots are in `<local-scratchpad>/` as `review_*.png`; the 390 px views are the `review_m_*.png` files. The contrast script is `<local-scratchpad>/cr.py`.
