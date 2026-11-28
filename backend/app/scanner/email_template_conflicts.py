from dataclasses import dataclass

from app.scanner.dto import QualityFinding
from app.scanner.duplicate_id_conflict import detect_duplicate_id_conflict


@dataclass
class EmailTemplateRow:
    module_id: int
    module_name: str
    template_id: str


def detect_email_template_id_conflicts(templates: list[EmailTemplateRow]) -> list[tuple[int, QualityFinding]]:
    """Cross-module email_templates.xml conflicts: two or more modules
    declaring a `<template>` with the exact same id. Unlike cache_type_conflict
    (which only fires when the backing `instance` genuinely disagrees, since a
    same-name cache.xml re-declaration is a legitimate cosmetic-override
    pattern), this fires on ANY cross-module duplicate id -- an email
    template's id is Magento's sole merge key, so a duplicate is always
    either a real conflict or a content-identical no-op, never a benign
    "same id, different metadata" case. Same-author restatement of the
    identical id is not flagged, only a real cross-module collision.
    """
    return detect_duplicate_id_conflict(
        templates,
        "template_id",
        "email_template_id_conflict",
        lambda template_id, who: (
            f'Multiple modules declare the same etc/email_templates.xml `<template id="{template_id}">`: '
            f"{who} — Magento merges email templates by id globally; the last-loaded module's "
            "declaration silently wins."
        ),
    )
