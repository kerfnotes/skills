<div align="center">
  <img src="docs/images/logo.svg" width="112" alt="Clayprint" />
  <h1>Clayprint</h1>
  <p><b>Put a script in, get back decks and reports where every page makes a claim and cites its source.</b></p>
  <p><a href="README.md">繁體中文</a> · English</p>
  <a href="https://github.com/kerfnotes/skills/stargazers"><img src="https://img.shields.io/github/stars/kerfnotes/skills?style=flat-square" alt="Stars"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue.svg?style=flat-square" alt="License"></a>
  <img src="https://img.shields.io/badge/node-%E2%89%A522.7-555?style=flat-square" alt="Node 22.7+">
  <a href="https://youtu.be/dIQ2amlA6HY"><img src="https://img.shields.io/badge/YouTube-Kerf-red?style=flat-square&logo=youtube" alt="YouTube"></a>
</div>

<br/>

<div align="center">
  <img src="docs/images/overview.svg" width="960" alt="One Clayprint run: script, claims, layouts, charts, build, check numbers, preview, deliver" />
</div>

## Why

Getting AI to make slides is easy. Getting slides you can take into a meeting is not: every title should be a claim, not "Background" or "Findings"; every number on a chart should trace back to the script; every page should state its source, unit and period. Clayprint builds those rules into a workflow and checking scripts that Codex or Claude Code runs for you. You give it a script and its purpose; it delivers PowerPoint (native charts whose numbers you can edit in PowerPoint), an HTML report or SVG charts, and looks at every page preview before handing them over.

Intro video: [From need to your own tool](https://youtu.be/dIQ2amlA6HY) (YouTube, 8:39, Traditional Chinese) on how Clayprint grew out of repeated dissatisfaction, and how to check what AI produces.

## Examples

The three showcase scripts use public data. Every number was traced to a primary source, then checked independently by a second model. All images below are generated directly from `examples/showcase/`, with no manual retouching. The decks are in Traditional Chinese.

**Taiwan's AI server export boom** (decision deck, [script](examples/showcase/ai-exports.md) · [story.json](examples/showcase/ai-exports.json)): Ministry of Finance customs statistics, DGBAS national accounts

| | |
| --- | --- |
| ![Executive summary: plan for structural demand, track concentration monthly](docs/images/ai-summary.png) | ![Grouped bars: computers overtake integrated circuits as a share of exports](docs/images/ai-goods.png) |
| Executive summary: recommendation left, three supporting numbers right | Grouped bars: computers overtake ICs for the first time |
| ![Dumbbell: the US replaces China and Hong Kong as the top export market](docs/images/ai-markets.png) | ![Bars with negatives: 2025 contributions to GDP growth](docs/images/ai-growth.png) |
| Dumbbell: two periods and the gap | Positive and negative bars: exports add most, imports take back over half |

**How typhoon days off are decided** (explainer, [script](examples/showcase/typhoon-day.md) · [story.json](examples/showcase/typhoon-day.json)): Taiwan's regulation on suspending work and classes for natural disasters

| | |
| --- | --- |
| ![Statement page: meeting a threshold does not force a day off](docs/images/typhoon-statement.png) | ![Table: rainfall thresholds for 22 cities and counties fall into three groups](docs/images/typhoon-table.png) |
| With no data, open with one sentence to remember | Table: rainfall thresholds for 22 cities and counties |
| ![Process: five steps from forecast to announcement](docs/images/typhoon-process.png) | ![Process: three announcement deadlines](docs/images/typhoon-deadlines.png) |
| Process: the step where the decision is made is highlighted | Three announcement deadlines |

**The global energy transition** (chart showcase, [script](examples/showcase/energy.md) · [story.json](examples/showcase/energy.json)): Ember, IEA (CC BY 4.0)

| | |
| --- | --- |
| ![Slope chart: solar capacity overtakes wind in ten years](docs/images/energy-slope.png) | ![100% stacked bars: wind and solar rise from 4.5% to 17.3% of generation](docs/images/energy-mix.png) |
| Slope chart: a crossover between two periods | 100% stacked bars: how the generation mix shifted |
| ![Small multiples: EV share in four markets](docs/images/energy-ev.png) | ![Waterfall: which sources met 2025 demand growth](docs/images/energy-bridge.png) |
| Small multiples: shared axis, separate trends | Waterfall: where new electricity came from |
| ![Ranked bars: top five solar generators in 2025](docs/images/energy-rank.png) | ![Option comparison: structural demand versus cyclical peak](docs/images/ai-compare.png) |
| Ranked bars with a computed key number | Option comparison: the recommended column is tinted (AI deck, page 8) |

The same AI exports script also becomes an HTML report ([ai-exports-report.html](examples/showcase/ai-exports-report.html)) to forward or print to PDF: white paper with a wide left margin, the 「圖 N」 (Figure N) label and title above each chart, notes and source below, a page footer, and sections that run on without page breaks.

<img src="docs/images/report.png" alt="HTML report: cover, contents, summary numbers and export line chart" width="480">

The showcase only organises public figures and is not investment or policy advice. Data were checked on 2026-10-22; later official revisions are not reflected. To reproduce after installing:

```sh
node evals/check.mjs examples/showcase/energy.json examples/showcase/energy.md
node scripts/pptx.js examples/showcase/energy.json out/energy.pptx
node scripts/preview.js out/energy.pptx out/energy
node scripts/pdf.js examples/showcase/ai-exports-report.html out/ai-exports
```

## How it checks itself

| Stage | What happens | Handled by |
| :--- | :--- | :--- |
| Claims | Each page starts with one `claim` its content can support, then picks a layout that holds it up; if it cannot, change the layout or cut the page | `SKILL.md`, [layouts.md](references/layouts.md) |
| Charts | 24 chart types grouped by the question they answer: ranking, trend, composition, distribution, sensitivity, relationship, drop-off, lookup | [charts.md](references/charts.md) |
| Numbers | Every number on screen must appear in the script or come from an add/subtract line on the same page; otherwise the build stops | `evals/check.mjs`, `evals/check-report.mjs` |
| Fit | Estimates whether text fits each box using the design layer's glyph widths; warns on orphans and overflow instead of shrinking type | `scripts/pptx.js` |
| Preview | Renders each page and a contact sheet through PowerPoint or LibreOffice, then reviews claim, emphasis and reading order page by page | `scripts/preview.js` |
| Print | Prints the report to PDF with Chrome, Edge or another Chromium browser and warns about underfilled pages, split figures or tables, and right-edge overflow | `scripts/pdf.js` |

Passing the checks only means numbers and fit are fine; meaning, overlaps and whether the story holds still need a look at the pages.

## Working with it

When you hand over a script, say who it is for and what judgement or decision it should support. The same script makes different trade-offs for different purposes.

| In the video | Files | Change when |
| --- | --- | --- |
| Instructions for the AI | `SKILL.md`, `references/` | Purpose, content flow or scope changes |
| Design settings | `design/tokens.json`, `design/brief.md` | Colours, fonts, sizes, spacing or line widths change |
| Code | `scripts/` | Chart types, layouts or outputs change |
| Checks | `tests/`, `examples/`, `evals/` | A new problem appears or a new example is needed |

`scripts/pptx.js` reads `story.json` and the design layer; `scripts/report.js` reads `report.json` and the design layer for the HTML report, and `scripts/pdf.js` prints it to PDF; SVG charts read chart JSON and the design layer. To change the look or the workflow, see [make it yours](docs/make-it-yours.md) (Traditional Chinese).

## Install with your agent

Give this to Codex or Claude Code:

```text
Install Clayprint (skills/kerf-clayprint) from https://github.com/kerfnotes/skills into this project.
Read skills/kerf-clayprint/docs/install.md first, pick the install path for the agent in use,
run the environment check, package install and example verification yourself,
then report the install path, version and verification results.
```

It needs Node **22.7.0 or later**, with no API key or build step. The project path is `.agents/skills/kerf-clayprint/` for Codex and `.claude/skills/kerf-clayprint/` for Claude Code. The whole `skills/kerf-clayprint/` folder is the skill; keep `SKILL.md`, `scripts/`, `references/`, `design/` and the rest. The [install guide](docs/install.md) (Traditional Chinese) covers download, reinstalling, missing Node, and the acceptance checks for building and previewing.

With the [`skills`](https://www.npmjs.com/package/skills) CLI you can also pick from the whole repo:

```sh
npx skills add kerfnotes/skills --list
```

## Use it

After installing, just ask:

```text
Use Clayprint to turn this script into a deck for my manager to decide whether to extend the pilot
Turn these meeting notes into a printable HTML report
Make this script a pre-read deck; people will read it on their own before the meeting, with no presenter
```

A pre-read deck uses smaller type and fits more on each page, and what a presenter would say goes on the page itself; see [read decks](references/layouts.md#閱讀型簡報) (Traditional Chinese).

Or invoke `$kerf-clayprint` in Codex and `/kerf-clayprint` in Claude Code.

## Known limits

- [PowerPoint editing limits](docs/design-diff.md): only some charts support "Edit Data"; SVG charts must be regenerated from their data.
- LibreOffice previews may substitute fonts. The PowerPoint font comes from the design layer's `font.slide` (Microsoft JhengHei by default); width estimates are calibrated for it, so check line breaks after switching fonts, and make sure recipients have the font.
- Chinese number words and date ranges are not checked automatically; verify them against the script by hand.
- The number check only confirms that on-screen numbers come from the script, not that the script is right; check the script's numbers against primary sources.

License: [MIT](LICENSE). Sources and licences for `examples/showcase/` are listed in each script's 來源 (Sources) section; the other examples in `examples/` are fictional and used for tests.
