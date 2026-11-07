from pathlib import Path

from lxml import etree

from app.scanner.dto import CronJobEntry


def parse_crontab_xml(path: Path) -> list[CronJobEntry]:
    """Parse a module's etc/crontab.xml into structured facts — scheduled jobs a
    module registers, with their backing class/method and cron schedule. Same role
    lxml plays for di.xml/events.xml: facts come from the parser, not the LLM.
    """
    if not path.is_file():
        return []

    try:
        root = etree.parse(str(path)).getroot()
    except etree.XMLSyntaxError:
        return []

    jobs: list[CronJobEntry] = []
    for job_el in root.findall(".//job"):
        job_name = job_el.get("name")
        instance_class = job_el.get("instance")
        method = job_el.get("method")
        if not job_name or not instance_class or not method:
            continue
        schedule_el = job_el.find("schedule")
        jobs.append(
            CronJobEntry(
                job_name=job_name,
                instance_class=instance_class,
                method=method,
                schedule=schedule_el.text.strip() if schedule_el is not None and schedule_el.text else None,
            )
        )
    return jobs
