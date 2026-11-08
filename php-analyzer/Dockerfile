# alpine:edge (not a numbered release) is the only Alpine base with php83,
# php84, AND php85 all packaged as separate, co-installable apk packages at
# once — confirmed directly: alpine:3.21/3.22 only go up to php84, no php85
# yet. Installed side by side, not just one version, because a scanned
# module's own composer.json php requirement varies module to module, and
# its real vendor/autoload.php (loaded for bitexpert/phpstan-magento's class
# resolution) enforces that requirement strictly via Composer's own generated
# platform_check.php — no single fixed interpreter version can satisfy every
# scanned module. app/scanner/php_analyzer_client.py's _pick_php_binary picks
# which of these three actually runs each tool, per module.
FROM alpine:edge

RUN apk add --no-cache git unzip \
    php83 php83-phar php83-mbstring php83-tokenizer php83-ctype php83-dom \
        php83-xml php83-xmlwriter php83-simplexml php83-curl php83-openssl php83-iconv \
    php84 php84-phar php84-mbstring php84-tokenizer php84-ctype php84-dom \
        php84-xml php84-xmlwriter php84-simplexml php84-curl php84-openssl php84-iconv \
    php85 php85-phar php85-mbstring php85-tokenizer php85-ctype php85-dom \
        php85-xml php85-xmlwriter php85-simplexml php85-curl php85-openssl php85-iconv \
    && ln -sf /usr/bin/php84 /usr/bin/php \
    && php -r "copy('https://getcomposer.org/installer', 'composer-setup.php');" \
    && php composer-setup.php --install-dir=/usr/local/bin --filename=composer \
    && rm composer-setup.php

WORKDIR /opt/analyzer

COPY php-analyzer/composer.json php-analyzer/composer.lock* ./
# dealerdirect/phpcodesniffer-composer-installer (a composer plugin,
# allow-listed below) already registers every installed phpcs standard's
# path automatically on install — no manual `phpcs --config-set
# installed_paths` needed. A previous hardcoded override here referenced
# vendor/phpcompatibility/php-compatibility, which no longer exists after
# magento/magento-coding-standard's major-version bump (it now depends on
# magento/php-compatibility-fork instead) — confirmed the override was
# actively wrong, not just redundant, and removed it rather than updating
# the hardcoded path again next time a dependency renames.
# --prefer-source (git clone over github.com) instead of the default
# --prefer-dist (a zipball generated on demand by api.github.com) — confirmed
# directly, repeatedly, the same day this was changed: --prefer-dist kept
# failing with curl error 28/56 timeouts and HTTP 504s against
# api.github.com's zipball endpoint for this exact dependency set, while
# --prefer-source succeeded reliably every time against the same packages.
# git is already installed above specifically for this.
#
# Optional build secret: if a `github_token` secret is passed at build time
# (docker build --secret id=github_token,src=<file>), authenticate Composer's
# GitHub requests with it — GitHub's unauthenticated API tier is always more
# exposed to rate limits/degradation than the authenticated one (confirmed
# directly against a real, officially-acknowledged GitHub incident the same
# day: "increase in timeouts for some unauthenticated users"). Silently a
# no-op when the secret isn't provided (every existing build, including
# CI), via `|| true` — never required.
RUN --mount=type=secret,id=github_token \
    (test -s /run/secrets/github_token \
        && composer config -g github-oauth.github.com "$(cat /run/secrets/github_token)" \
        || true) \
    && composer install --no-dev --no-interaction --prefer-source --no-progress

COPY php-analyzer/public ./public
COPY php-analyzer/rector.php ./rector.php
COPY php-analyzer/phpstan.neon ./phpstan.neon
COPY php-analyzer/magento-core.stub ./magento-core.stub
COPY php-analyzer/noop-autoload.php ./noop-autoload.php

# Mirrors the same fixture path backend/Dockerfile bakes in, so k8s's
# scan-cronjob flow (which only ever scans that path) works against this
# sidecar too with no new shared k8s volume.
COPY backend/tests/fixtures/demo-store /app/tests/fixtures/demo-store

EXPOSE 8080

CMD ["php", "-S", "0.0.0.0:8080", "-t", "public"]
