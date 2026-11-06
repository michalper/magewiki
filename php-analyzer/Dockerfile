FROM php:8.3-cli-alpine

RUN apk add --no-cache git unzip \
    && php -r "copy('https://getcomposer.org/installer', 'composer-setup.php');" \
    && php composer-setup.php --install-dir=/usr/local/bin --filename=composer \
    && rm composer-setup.php

WORKDIR /opt/analyzer

COPY php-analyzer/composer.json ./
RUN composer install --no-dev --no-interaction --prefer-dist --no-progress \
    && vendor/bin/phpcs --config-set installed_paths /opt/analyzer/vendor/magento/magento-coding-standard,/opt/analyzer/vendor/phpcompatibility/php-compatibility

COPY php-analyzer/public ./public
COPY php-analyzer/rector.php ./rector.php
COPY php-analyzer/phpstan.neon ./phpstan.neon
COPY php-analyzer/magento-core.stub ./magento-core.stub

# Mirrors the same fixture path backend/Dockerfile bakes in, so k8s's
# scan-cronjob flow (which only ever scans that path) works against this
# sidecar too with no new shared k8s volume.
COPY backend/tests/fixtures/demo-store /app/tests/fixtures/demo-store

EXPOSE 8080

CMD ["php", "-S", "0.0.0.0:8080", "-t", "public"]
