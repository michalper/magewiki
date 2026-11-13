<?php
namespace Vendor\QualityChecks\Helper;

/**
 * @deprecated Use a proper logger instead.
 */
class Debug
{
    // Fixture-only -- the same literal already committed elsewhere in this
    // repo's own tests (backend/tests/scanner/test_secrets_scanner.py) to
    // trigger the hardcoded_secret check. Not a real credential.
    private $exampleAwsKey = 'AKIAABCDEFGHIJKLMNOP';

    public function dump($value)
    {
        $unused = 1;
        var_dump($value);
        return $undefinedVariable;
    }
}
