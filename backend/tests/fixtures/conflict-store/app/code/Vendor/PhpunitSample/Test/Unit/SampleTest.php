<?php
namespace Vendor\QualityChecks\Test\Unit;

use PHPUnit\Framework\TestCase;

/**
 * Deliberately failing -- e2e fixture coverage for phpunit_failure. No
 * module autoloading needed: this extends PHPUnit's own bundled
 * TestCase directly, nothing from Vendor\QualityChecks itself.
 */
class SampleTest extends TestCase
{
    public function testItDeliberatelyFails(): void
    {
        $this->assertSame(1, 2, 'deliberately failing assertion for e2e fixture coverage');
    }
}
