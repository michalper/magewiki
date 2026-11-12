from pathlib import Path

from lxml import etree


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
    existed.
    """
    if not path.is_file():
        return None

    try:
        return etree.parse(str(path)).getroot()
    except etree.XMLSyntaxError:
        return None
