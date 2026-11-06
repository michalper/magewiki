from pathlib import Path

from app.scanner.secrets_scanner import scan_hardcoded_secrets


def test_scan_hardcoded_secrets_detects_aws_key(tmp_path: Path):
    (tmp_path / "Config.php").write_text(
        "<?php\n$key = 'AKIAABCDEFGHIJKLMNOP';\n"
    )
    findings = scan_hardcoded_secrets(tmp_path)

    assert len(findings) == 1
    assert findings[0].check_type == "hardcoded_secret"
    assert findings[0].severity == "blocking"
    assert "AWS access key" in findings[0].message
    # The actual key value is never stored, only a short redacted preview.
    assert "AKIAABCDEFGHIJKLMNOP" not in findings[0].message
    assert "AKI" in findings[0].message


def test_scan_hardcoded_secrets_detects_generic_password_literal(tmp_path: Path):
    (tmp_path / "Config.php").write_text(
        "<?php\n$password = 'hunter2hunter2';\n"
    )
    findings = scan_hardcoded_secrets(tmp_path)

    assert len(findings) == 1
    assert "hunter2hunter2" not in findings[0].message


def test_scan_hardcoded_secrets_ignores_placeholders(tmp_path: Path):
    (tmp_path / "Config.php").write_text(
        "<?php\n$password = 'changeme';\n$token = 'your_token_here';\n"
    )
    assert scan_hardcoded_secrets(tmp_path) == []


def test_scan_hardcoded_secrets_with_no_secrets(tmp_path: Path):
    (tmp_path / "Clean.php").write_text("<?php\nclass Clean {}\n")
    assert scan_hardcoded_secrets(tmp_path) == []
