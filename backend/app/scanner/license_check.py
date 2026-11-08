from app.scanner.dto import QualityFinding

# Strong copyleft families only -- GPL/AGPL/SSPL carry real "if you distribute
# this, you must open-source your own code too" obligations relevant to a
# commercial store bundling third-party modules. LGPL is deliberately excluded:
# it's widely treated as lower-risk (dynamic-linking-style use is normally
# fine), and including it would trade a concrete, certain signal for a noisy,
# debatable one -- the same "flag a concrete, certain conflict" pragmatism
# used throughout this file's quality checks.
_RISKY_LICENSE_PREFIXES = ("GPL-", "AGPL-", "SSPL-")


def check_license_risk(license: list[str] | None) -> list[QualityFinding]:
    """Flag a module whose own composer.json declares a strong-copyleft
    license. A missing license entirely is already covered by
    composer_completeness_findings()'s "composer.json is missing license"
    check -- this only adds the complementary signal: a license that *is*
    declared, but carries real redistribution obligations a commercial
    Magento store should actually review.
    """
    if not license:
        return []

    risky = sorted({lic for lic in license if lic.upper().startswith(_RISKY_LICENSE_PREFIXES)})
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
