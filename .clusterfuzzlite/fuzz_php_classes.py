"""ClusterFuzzLite harness for the tree-sitter-php based class/method
extractor: a scanned module's own .php files are untrusted input (the module
itself is never executed, but its source is parsed), and parse_php_source
has no documented exception contract -- it's expected to handle arbitrary
byte input without raising. A couple of its own "never happens" assumptions
about tree-sitter-php's grammar (see php_classes.py's `# pragma: no cover -
defensive` comments) are exactly the kind of claim fuzzing can falsify over
a much wider input space than the tests that verified them by hand.
"""
import atheris
import sys
import tempfile
from pathlib import Path

with atheris.instrument_imports():
    from app.scanner.php_classes import parse_php_source
    from app.scanner.config_php import parse_config_php


def TestOneInput(data: bytes) -> None:
    parse_php_source(data, "Fuzz.php")

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "config.php"
        path.write_bytes(data)
        parse_config_php(path)


atheris.Setup(sys.argv, TestOneInput)
atheris.Fuzz()
