# Security Policy

MageWiki-AI is a portfolio project maintained by one person, with no SLA on
response time — but real vulnerability reports are taken seriously and
triaged as soon as possible.

## Reporting a vulnerability

Please use GitHub's [private vulnerability
reporting](https://github.com/michalper/magewiki/security/advisories/new)
(the "Report a vulnerability" button on this repo's Security tab) rather than
a public issue. This keeps the report and any fix work private until a patch
is out.

Include what you'd expect in any report: the affected component (`backend`,
`frontend`, or `php-analyzer`), a minimal reproduction, and the impact as you
see it.

## Scope

- The application code in this repository (`backend/`, `frontend/`,
  `php-analyzer/`) and its own configuration (`k8s/`, `docker-compose.yml`,
  the `Dockerfile`s).

Out of scope: third-party dependencies with no code of this project's own
involved (report those upstream instead) and findings already called out as
accepted, known tradeoffs in `CLAUDE.md` (e.g. the monthly LLM budget check's
documented soft-limit race).

## Supported versions

Only the latest release and `main` are supported. This project does not
maintain long-term support branches for older tags.

## Verifying a release

Every GitHub Release from `v1.12.0` onward includes a source archive
(`magewiki-vX.Y.Z.tar.gz`) and a Sigstore bundle
(`magewiki-vX.Y.Z.tar.gz.sigstore.json`) signed keylessly with
[cosign](https://docs.sigstore.dev/cosign/installation/) — there is no
long-lived private signing key anywhere; the certificate is short-lived and
tied to the identity that signed it (this repo's own `release.yml` workflow
run, via GitHub Actions' own OIDC token).

To verify a downloaded archive:

```sh
cosign verify-blob \
  --bundle magewiki-vX.Y.Z.tar.gz.sigstore.json \
  --certificate-identity-regexp 'https://github\.com/michalper/magewiki/' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com \
  magewiki-vX.Y.Z.tar.gz
```

`cosign` reports the exact signing identity from the certificate if you'd
rather confirm it by eye than match a regexp — open
`magewiki-vX.Y.Z.tar.gz.sigstore.json` and inspect the embedded certificate.
