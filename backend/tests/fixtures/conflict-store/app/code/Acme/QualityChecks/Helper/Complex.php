<?php
namespace Acme\QualityChecks\Helper;

class Complex
{
    // Deliberately high cyclomatic complexity -- a candidate trigger for
    // phpmetrics_issue (PhpMetrics' own built-in complexity/"probably
    // bugged" violation threshold), to be verified against the real
    // php-analyzer sidecar rather than assumed.
    public function classify($value)
    {
        if ($value === 1) {
            return 'one';
        } elseif ($value === 2) {
            return 'two';
        } elseif ($value === 3) {
            return 'three';
        } elseif ($value === 4) {
            return 'four';
        } elseif ($value === 5) {
            return 'five';
        } elseif ($value === 6) {
            return 'six';
        } elseif ($value === 7) {
            return 'seven';
        } elseif ($value === 8) {
            return 'eight';
        } elseif ($value === 9) {
            return 'nine';
        } elseif ($value === 10) {
            return 'ten';
        } elseif ($value === 11) {
            return 'eleven';
        } elseif ($value === 12) {
            return 'twelve';
        } else {
            return 'many';
        }
    }
}
