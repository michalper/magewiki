# Governance

MageWiki-AI is a solo-maintained portfolio project. This file documents how
decisions get made and who's responsible for what — the OpenSSF Best
Practices Badge's silver-level criteria ask for this to be written down
explicitly, not just true in practice.

## Decision model

There is one maintainer, [Michał Per](https://github.com/michalper), who
makes all final decisions: what gets built, what gets merged, what gets
released. There is no voting process or steering committee — a project this
size doesn't need one yet.

Anyone can propose a change via a pull request or an issue (see
[CONTRIBUTING.md](CONTRIBUTING.md)). The maintainer reviews and decides;
there's no formal RFC process for smaller changes. A substantial
architecture change gets written up first — this project's own working
method (see `CLAUDE.md`'s "Working method" section) is to plan before
building, and that applies to the maintainer's own work too, not just
outside contributions.

## Roles and responsibilities

| Role | Who | Responsibilities |
|---|---|---|
| Maintainer | Michał Per | Final say on direction, code review, merging PRs, cutting releases, triaging issues, responding to security reports (see [SECURITY.md](SECURITY.md)) |
| Collaborator | [moston](https://github.com/moston) | Write access to the repository — can accept pull requests, triage and close issues, and cut a release if the maintainer is unavailable. Not involved in project direction/decisions. |

### Continuity

The collaborator above has repository `push` access (confirmed: not
restricted by branch protection beyond the same required status checks
everyone, including the maintainer, goes through), which is enough to keep
the three things that matter most running if the maintainer becomes
unavailable: accepting pull requests, triaging/closing issues, and cutting
a release. What they don't have: admin access to repository settings or
secrets (CI tokens, deployment credentials), and no decision-making
authority over project direction — that stays with the maintainer. This is
a real, if partial, answer to bus-factor risk, not a claim of a fully
redundant second maintainer.

## How this changes

This file gets updated the same way any other change does: a PR, reviewed
and merged by the maintainer. If a second maintainer is ever added with real
authority (not just a collaborator invite), this file is where that gets
recorded.
