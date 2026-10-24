# Issue tracker: GitHub

Specs and tickets live in GitHub Issues for `kerfnotes/skills`. Use `gh` with the explicit `--repo kerfnotes/skills` option, or the matching repository API path.

## Operations

- Read issues with `gh issue view NUMBER --repo kerfnotes/skills --comments` and request JSON fields when structured state is needed.
- Create and edit issues with a prepared UTF-8 body file and `--body-file`; preserve real newlines. Avoid interpolating multiline content into shell commands.
- Use `ready-for-agent` for a decision-complete spec or ticket. Keep parent and blocking relationships visible in each ticket body.
- Add GitHub native sub-issue and dependency relationships when supported. Dependencies use the blocker's numeric database ID, not its issue number. If unsupported, retain the explicit `Blocked by` list in the issue body and report the limitation.
- A ticket is ready only after every blocker is resolved. Work on independent frontier tickets concurrently when useful.
- Close a ticket with `gh issue close` after its acceptance criteria are met, leaving a concise implementation and validation receipt. State whether commits are local or pushed; closing an issue does not imply release or publication of code.
- Close a parent spec only when all required tickets and final integration acceptance are complete.

## Publication boundary

Publishing specs/tickets, local commits, pushing code and creating a PR are separate permissions. Reuse explicit authorization from the current conversation. Do not create a PR as a prerequisite for closing work when the user authorized local integration only.

## Pull requests as a triage surface

PRs as a request surface: no.
