from app.scanner.dto import QualityFinding

# Strong copyleft families only -- GPL/AGPL/SSPL carry real "if you distribute
# this, you must open-source your own code too" obligations relevant to a
# commercial store bundling third-party modules. LGPL is deliberately excluded:
# it's widely treated as lower-risk (dynamic-linking-style use is normally
# fine), and including it would trade a concrete, certain signal for a noisy,
# debatable one -- the same "flag a concrete, certain conflict" pragmatism
# used throughout this file's quality checks. This is only the *default* --
# what counts as "risky" is a legal/business judgment call that varies by
# operator, so it's exposed as the LICENSE_RISK_PREFIXES setting
# (app/config.py) rather than hardcoded; this tuple is just the fallback when
# that setting is left at its default.
DEFAULT_RISKY_LICENSE_PREFIXES = ("GPL-", "AGPL-", "SSPL-")


def check_license_risk(
    license: list[str] | None,
    risky_prefixes: tuple[str, ...] = DEFAULT_RISKY_LICENSE_PREFIXES,
) -> list[QualityFinding]:
    """Flag a module whose own composer.json declares a license matching one
    of risky_prefixes (default: strong-copyleft families). A missing license
    entirely is already covered by composer_completeness_findings()'s
    "composer.json is missing license" check -- this only adds the
    complementary signal: a license that *is* declared, but carries real
    redistribution obligations a commercial Magento store should actually
    review.
    """
    if not license or not risky_prefixes:
        return []

    risky = sorted({lic for lic in license if lic.upper().startswith(risky_prefixes)})
    if not risky:
        return []

    return [
        QualityFinding(
            check_type="license_risk",
            severity="warning",
            file_path="composer.json",
            line=None,
            message=(
                f"Declares a strong-copyleft license ({', '.join(risky)}) — bundling this into a "
                "commercial store may carry real redistribution obligations worth reviewing."
            ),
        )
    ]
