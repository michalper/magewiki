from pathlib import Path

from lxml import etree

from app.scanner.discovery import is_safe_to_read


def parse_xml_root(path: Path) -> etree._Element | None:
    """The is_file()/XMLSyntaxError guard shared by every one of this
    project's declarative-XML parsers that reads a single root and fails
    open on anything else (acl.xml, di.xml, events.xml, system.xml,
    webapi.xml, db_schema.xml, crontab.xml, indexer.xml, mview.xml, plus
    queue_config.py's three files -- see each parser's own docstring for
    the fact shape it extracts from the returned root). module.xml is the
    one declarative-XML parser that deliberately doesn't use this: a
    missing/malformed module.xml is a hard error there
    (InvalidModuleXmlError), not a "nothing to report" case. Returns None
    for a missing or malformed file, same "doesn't exist / skip" handling
    every parser using this helper already used individually before it
    existed. Also returns None for a symlink -- see is_safe_to_read's own
    docstring for why a scanned module's declarative-XML file can't be
    trusted to actually be the file it claims to be.
    """
    if not path.is_file() or not is_safe_to_read(path):
        return None

    try:
        return etree.parse(str(path)).getroot()
    except (etree.XMLSyntaxError, OSError):
        # lxml raises OSError, not XMLSyntaxError, for some malformed
        # encoding declarations (e.g. a <?xml encoding=...?> that doesn't
        # match the file's actual bytes) when parsing from a file path --
        # found by fuzzing, not by any XML sample written by hand.
        return None
