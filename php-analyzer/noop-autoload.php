<?php

// Fallback bootstrap file for phpstan.neon's bootstrapFiles when the scanned
// module/store has no real vendor/autoload.php of its own (e.g. a minimal
// fixture) — PHPStan's bootstrapFiles require()s the path unconditionally,
// so it must always resolve to something, even a no-op.
