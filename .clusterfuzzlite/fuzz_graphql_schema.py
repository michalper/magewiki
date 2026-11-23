"""ClusterFuzzLite harness for etc/schema.graphqls parsing -- a scanned
module's own file, so untrusted input. parse_graphql_schema already catches
graphql-core's own GraphQLSyntaxError and fails open to []; anything else
raised here is a real bug, not expected behavior.
"""
import atheris
import sys
import tempfile
from pathlib import Path

with atheris.instrument_imports():
    from app.scanner.graphql_schema import parse_graphql_schema


def TestOneInput(data: bytes) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "schema.graphqls"
        path.write_bytes(data)
        parse_graphql_schema(path)


atheris.Setup(sys.argv, TestOneInput)
atheris.Fuzz()
