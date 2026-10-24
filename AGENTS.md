# Agent skills

## Issue tracker

Specs and tickets live in GitHub Issues for `kerfnotes/skills`. Use the `gh` CLI. See [tracker conventions](docs/agents/issue-tracker.md).

## Triage labels

Use the five default triage labels. See [label vocabulary](docs/agents/triage-labels.md).

## Domain docs

Use a single-context glossary and ADR layout when those files exist. See [domain guidance](docs/agents/domain.md).

## Working rules

- Preserve unrelated work and the user's existing choices. Use natural Taiwan Traditional Chinese when communicating with this user.
- Commit, push, publication, release and deployment require explicit user authorization. Authorization for local commits does not authorize a push or PR.
- Use the project's existing design system. Test visible behavior and public contracts; do not treat mocks or structural checks as proof of real-provider or device behavior.
- Follow instructions supplied in the active conversation when they grant narrower scope or specify the working method.
