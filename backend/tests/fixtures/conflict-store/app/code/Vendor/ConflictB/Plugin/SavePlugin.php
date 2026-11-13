<?php
namespace Vendor\ConflictB\Plugin;

class SavePlugin
{
    public function aroundSave($subject, callable $proceed)
    {
        return $proceed();
    }
}
