from pathlib import Path

from app.scanner.crontab_xml import parse_crontab_xml

_CRONTAB_XML = """<?xml version="1.0"?>
<config xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:noNamespaceSchemaLocation="urn:magento:module:Magento_Cron:etc/crontab.xsd">
    <group id="default">
        <job name="vendor_module_sample_job" instance="Vendor\\Module\\Cron\\SampleJob" method="execute">
            <schedule>0 2 * * *</schedule>
        </job>
    </group>
</config>
"""


def test_parse_crontab_xml(tmp_path: Path):
    path = tmp_path / "crontab.xml"
    path.write_text(_CRONTAB_XML, encoding="utf-8")

    jobs = parse_crontab_xml(path)

    assert len(jobs) == 1
    job = jobs[0]
    assert job.job_name == "vendor_module_sample_job"
    assert job.instance_class == "Vendor\\Module\\Cron\\SampleJob"
    assert job.method == "execute"
    assert job.schedule == "0 2 * * *"


def test_parse_crontab_xml_missing_file(tmp_path: Path):
    assert parse_crontab_xml(tmp_path / "crontab.xml") == []


def test_parse_crontab_xml_job_without_schedule(tmp_path: Path):
    path = tmp_path / "crontab.xml"
    path.write_text(
        '<?xml version="1.0"?>\n'
        '<config><group id="default">'
        '<job name="x" instance="Vendor\\Module\\Cron\\X" method="execute"/>'
        "</group></config>",
        encoding="utf-8",
    )

    jobs = parse_crontab_xml(path)

    assert len(jobs) == 1
    assert jobs[0].schedule is None
