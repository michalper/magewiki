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

This project doesn't yet have a second maintainer with commit access and
release authority, so it currently has a bus factor of 1 — if the
maintainer becomes unavailable, nobody else can create releases, accept
PRs, or respond to a vulnerability report until that's resolved.

## How this changes

This file gets updated the same way any other change does: a PR, reviewed
and merged by the maintainer. If a second maintainer is ever added with real
authority (not just a collaborator invite), this file is where that gets
recorded.
