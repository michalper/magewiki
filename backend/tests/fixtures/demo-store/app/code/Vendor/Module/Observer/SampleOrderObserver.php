<?php
declare(strict_types=1);

namespace Vendor\Module\Observer;

use Magento\Framework\Event\Observer as EventObserver;
use Magento\Framework\Event\ObserverInterface;

class SampleOrderObserver implements ObserverInterface
{
    public function execute(EventObserver $observer)
    {
        return $this;
    }
}
