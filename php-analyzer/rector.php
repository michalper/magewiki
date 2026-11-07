<?php

declare(strict_types=1);

use Rector\Config\RectorConfig;
use Rector\Set\ValueObject\LevelSetList;

return static function (RectorConfig $rectorConfig): void {
    $rectorConfig->sets([LevelSetList::UP_TO_PHP_81]);
    // The module path passed at analysis time may contain its own nested
    // vendor/ (composer-installed dependencies, tens of thousands of
    // files) — never analyze those, only the module's own source. Test/ is
    // excluded too: PHPUnit test code is a different quality concern than
    // the production code this check is meant to flag.
    $rectorConfig->skip(['*/vendor/*', '*/Test/*']);
};
