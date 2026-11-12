<?php
namespace Vendor\ConflictA\Plugin;

class SavePlugin
{
    public function aroundSave($subject, callable $proceed)
    {
        return $proceed();
    }
}
