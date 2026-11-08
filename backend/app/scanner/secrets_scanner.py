import re
from pathlib import Path

from app.scanner.discovery import walk_module_source_files
from app.scanner.dto import QualityFinding

# Filters out assignments that are obviously placeholders, not real secrets.
_PLACEHOLDER_RE = re.compile(
    r"(xxx|example|changeme|change_me|dummy|placeholder|your[_-]?\w*|todo|test(ing)?|redacted|sample|<|\{\{)",
    re.IGNORECASE,
)

# Branded patterns: specific enough that a match is almost never a false
# positive, unlike a generic high-entropy-string heuristic.
_BRANDED_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("AWS access key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("GitHub token", re.compile(r"gh[opsu]_[A-Za-z0-9]{36,}")),
    ("Slack token", re.compile(r"xox[baprs]-[0-9A-Za-z-]{10,}")),
    ("Stripe live key", re.compile(r"sk_live_[0-9A-Za-z]{24,}")),
    # The type prefix (RSA/EC/OPENSSH/DSA) is itself optional via the
    # trailing "?" -- PKCS#8 unencrypted keys use a PEM header with no type
    # prefix at all. No empty alternative inside the group itself (flagged
    # by SonarCloud python:S5842/S6323): that would be redundant with the
    # outer "?" and match the empty string pointlessly.
    ("PEM private key", re.compile(r"-----BEGIN (RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----")),
    ("Basic-auth URL credential", re.compile(r"[a-z][a-z0-9+.-]*://[^\s/'\"]+:[^\s/'\"@]+@")),
]

# A literal string assigned to something that looks like a credential —
# filtered through _PLACEHOLDER_RE above to cut false positives.
_GENERIC_SECRET_RE = re.compile(
    r"""(?i)\b(password|passwd|secret|api[_-]?key|token)\b\s*=>?\s*['"]([^'"]{6,})['"]"""
)


def _redact(value: str) -> str:
    return f"{value[:3]}...({len(value)} chars)"


def _line_of(source: str, offset: int) -> int:
    return source.count("\n", 0, offset) + 1


def _scan_text(source: str, relative_file_path: str) -> list[QualityFinding]:
    findings: list[QualityFinding] = []

    for label, pattern in _BRANDED_PATTERNS:
        for match in pattern.finditer(source):
            findings.append(
                QualityFinding(
                    check_type="hardcoded_secret",
                    severity="blocking",
                    file_path=relative_file_path,
                    line=_line_of(source, match.start()),
                    message=f"{label}: {_redact(match.group(0))}",
                )
            )

    for match in _GENERIC_SECRET_RE.finditer(source):
        value = match.group(2)
        if _PLACEHOLDER_RE.search(value):
            continue
        findings.append(
            QualityFinding(
                check_type="hardcoded_secret",
                severity="blocking",
                file_path=relative_file_path,
                line=_line_of(source, match.start()),
                message=f"hardcoded {match.group(1)}: {_redact(value)}",
            )
        )

    return findings


def scan_hardcoded_secrets(module_root: Path) -> list[QualityFinding]:
    """Pure regex over raw source text — no subprocess, no AST. The matched
    secret value is never stored, only a short redacted preview."""
    findings: list[QualityFinding] = []
    for php_file in walk_module_source_files(module_root):
        relative_file_path = str(php_file.relative_to(module_root))
        try:
            source = php_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        findings.extend(_scan_text(source, relative_file_path))
    return findings
