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


def test_scan_hardcoded_secrets_detects_a_pem_private_key_with_a_type_prefix(tmp_path: Path):
    # A PEM header literal used to test our own detector catching it, not a
    # real key -- gitleaks:allow
    (tmp_path / "Config.php").write_text("<?php\n// -----BEGIN RSA PRIVATE KEY-----\n")  # gitleaks:allow
    findings = scan_hardcoded_secrets(tmp_path)

    assert len(findings) == 1
    assert "PEM private key" in findings[0].message


def test_scan_hardcoded_secrets_detects_a_pkcs8_pem_private_key_with_no_type_prefix(tmp_path: Path):
    # PKCS#8 unencrypted keys have no RSA/EC/OPENSSH/DSA prefix at all --
    # the regex's optional group must still match a bare "PRIVATE KEY"
    # header, not just the prefixed variants. Same as above, a literal used
    # to test our own detector -- gitleaks:allow
    (tmp_path / "Config.php").write_text("<?php\n// -----BEGIN PRIVATE KEY-----\n")  # gitleaks:allow
    findings = scan_hardcoded_secrets(tmp_path)

    assert len(findings) == 1
    assert "PEM private key" in findings[0].message


def test_scan_hardcoded_secrets_ignores_placeholders(tmp_path: Path):
    (tmp_path / "Config.php").write_text(
        "<?php\n$password = 'changeme';\n$token = 'your_token_here';\n"
    )
    assert scan_hardcoded_secrets(tmp_path) == []


def test_scan_hardcoded_secrets_with_no_secrets(tmp_path: Path):
    (tmp_path / "Clean.php").write_text("<?php\nclass Clean {}\n")
    assert scan_hardcoded_secrets(tmp_path) == []


def test_scan_hardcoded_secrets_skips_a_file_that_vanishes_before_it_can_be_read(tmp_path: Path, monkeypatch):
    clean = tmp_path / "Clean.php"
    clean.write_text("<?php\nclass Clean {}\n")
    vanished = tmp_path / "Vanished.php"

    monkeypatch.setattr("app.scanner.secrets_scanner.walk_module_source_files", lambda root: [clean, vanished])

    assert scan_hardcoded_secrets(tmp_path) == []
