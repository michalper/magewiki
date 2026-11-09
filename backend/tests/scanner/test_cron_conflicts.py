from app.scanner.cron_conflicts import CronJobRow, detect_cron_job_conflicts


def _job(module_id, module_name, job_name="vendor_sample_job", instance_class="Vendor\\A\\Cron\\Sample", method="execute"):
    return CronJobRow(module_id=module_id, module_name=module_name, job_name=job_name, instance_class=instance_class, method=method)


def test_no_conflict_with_a_single_declarer():
    jobs = [_job(1, "Vendor_A")]
    assert detect_cron_job_conflicts(jobs) == []


def test_no_conflict_when_the_same_module_declares_it_twice_identically():
    jobs = [_job(1, "Vendor_A"), _job(1, "Vendor_A")]
    assert detect_cron_job_conflicts(jobs) == []


def test_no_conflict_when_job_names_differ():
    jobs = [_job(1, "Vendor_A", job_name="vendor_a_job"), _job(2, "Vendor_B", job_name="vendor_b_job")]
    assert detect_cron_job_conflicts(jobs) == []


def test_no_conflict_when_modules_agree_on_the_same_instance_and_method():
    jobs = [
        _job(1, "Vendor_A", instance_class="Vendor\\Shared\\Cron\\Sample", method="execute"),
        _job(2, "Vendor_B", instance_class="Vendor\\Shared\\Cron\\Sample", method="execute"),
    ]
    assert detect_cron_job_conflicts(jobs) == []


def test_flags_a_real_cross_module_cron_job_conflict():
    jobs = [
        _job(1, "Vendor_A", job_name="shared_job", instance_class="Vendor\\A\\Cron\\Sample", method="execute"),
        _job(2, "Vendor_B", job_name="shared_job", instance_class="Vendor\\B\\Cron\\Sample", method="execute"),
    ]

    findings = detect_cron_job_conflicts(jobs)

    assert {module_id for module_id, _ in findings} == {1, 2}
    for _, finding in findings:
        assert finding.check_type == "cron_job_conflict"
        assert finding.severity == "warning"
        assert "shared_job" in finding.message
        assert "Vendor_A -> Vendor\\A\\Cron\\Sample::execute" in finding.message
        assert "Vendor_B -> Vendor\\B\\Cron\\Sample::execute" in finding.message
