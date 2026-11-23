from pathlib import Path

from lxml import etree

from app.scanner.discovery import is_safe_to_read

# Shared by every lxml etree.parse() call in this project (here and in
# module_xml.py). A code-review pass flagged XXE (a scanned module's
# module.xml declaring `<!ENTITY x SYSTEM "file:///etc/passwd">` and
# expanding it into a persisted attribute) as a possible local-file-read --
# checked directly against the pinned lxml/libxml2 (6.1.3 / 2.14.6) rather
# than assumed: every combination of load_dtd/no_network/resolve_entities
# already rejects external-entity expansion outright (libxml2 itself raises
# "Attribute references external entity" / silently drops it in text
# content, even with every flag at its most permissive) -- this was never a
# live vulnerability against the version actually in use. Set explicitly
# anyway as cheap, correct defense-in-depth against a future lxml/libxml2
# downgrade or version where the library's own default differs.
HARDENED_XML_PARSER = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False)


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
        return etree.parse(str(path), parser=HARDENED_XML_PARSER).getroot()
    except (etree.XMLSyntaxError, OSError):
        # lxml raises OSError, not XMLSyntaxError, for some malformed
        # encoding declarations (e.g. a <?xml encoding=...?> that doesn't
        # match the file's actual bytes) when parsing from a file path --
        # found by fuzzing, not by any XML sample written by hand.
        return None
