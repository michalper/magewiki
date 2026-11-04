<?php
declare(strict_types=1);

namespace Vendor\Module\Plugin;

use Magento\Quote\Model\Quote\Address\Total\Collector;

class SampleCheckoutPlugin
{
    public function beforeSubmitAll(Collector $subject, $items)
    {
        return [$items];
    }
}
