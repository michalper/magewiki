# ClusterFuzzLite builder for the Python fuzz harnesses in this directory.
# Only backend/app's own real runtime parsers are exercised (lxml,
# tree-sitter-php, graphql-core) — fastapi/sqlalchemy/litellm etc. are never
# imported by app.scanner.*, so they're deliberately not installed here.
FROM gcr.io/oss-fuzz-base/base-builder-python

COPY . $SRC/magewiki
COPY .clusterfuzzlite/build.sh $SRC/build.sh
WORKDIR $SRC/magewiki
