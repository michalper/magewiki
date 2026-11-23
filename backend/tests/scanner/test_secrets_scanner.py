from app.scanner.secrets_scanner import scan_hardcoded_secrets


def test_scan_hardcoded_secrets_detects_aws_key():
    findings = scan_hardcoded_secrets({"Config.php": b"<?php\n$key = 'AKIAABCDEFGHIJKLMNOP';\n"})

    assert len(findings) == 1
    assert findings[0].check_type == "hardcoded_secret"
    assert findings[0].severity == "blocking"
    assert "AWS access key" in findings[0].message
    # The actual key value is never stored, only a short redacted preview.
    assert "AKIAABCDEFGHIJKLMNOP" not in findings[0].message
    assert "AKI" in findings[0].message


def test_scan_hardcoded_secrets_detects_generic_password_literal():
    findings = scan_hardcoded_secrets({"Config.php": b"<?php\n$password = 'hunter2hunter2';\n"})

    assert len(findings) == 1
    assert "hunter2hunter2" not in findings[0].message


def test_scan_hardcoded_secrets_detects_a_pem_private_key_with_a_type_prefix():
    # A PEM header literal used to test our own detector catching it, not a
    # real key -- gitleaks:allow
    findings = scan_hardcoded_secrets(
        {"Config.php": b"<?php\n// -----BEGIN RSA PRIVATE KEY-----\n"}  # gitleaks:allow
    )

    assert len(findings) == 1
    assert "PEM private key" in findings[0].message


def test_scan_hardcoded_secrets_detects_a_pkcs8_pem_private_key_with_no_type_prefix():
    # PKCS#8 unencrypted keys have no RSA/EC/OPENSSH/DSA prefix at all --
    # the regex's optional group must still match a bare "PRIVATE KEY"
    # header, not just the prefixed variants. Same as above, a literal used
    # to test our own detector -- gitleaks:allow
    findings = scan_hardcoded_secrets({"Config.php": b"<?php\n// -----BEGIN PRIVATE KEY-----\n"})  # gitleaks:allow

    assert len(findings) == 1
    assert "PEM private key" in findings[0].message


def test_scan_hardcoded_secrets_ignores_placeholders():
    source = b"<?php\n$password = 'changeme';\n$token = 'your_token_here';\n"
    assert scan_hardcoded_secrets({"Config.php": source}) == []


def test_scan_hardcoded_secrets_with_no_secrets():
    assert scan_hardcoded_secrets({"Clean.php": b"<?php\nclass Clean {}\n"}) == []
