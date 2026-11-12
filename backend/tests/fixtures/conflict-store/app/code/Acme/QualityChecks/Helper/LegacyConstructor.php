<?php
namespace Acme\QualityChecks\Helper;

// A plain constructor-assigns-to-property pattern -- a candidate trigger for
// php_compat_issue (Rector's ClassPropertyAssignToConstructorPromotionRector,
// part of the Php80 set bundled into LevelSetList::UP_TO_PHP_81), to be
// verified against the real php-analyzer sidecar rather than assumed.
class LegacyConstructor
{
    private $value;

    public function __construct($value)
    {
        $this->value = $value;
    }

    public function getValue()
    {
        return $this->value;
    }
}
