from pathlib import Path

from lxml import etree


def parse_xml_root(path: Path) -> etree._Element | None:
    """The is_file()/XMLSyntaxError guard shared by this project's simpler,
    single-root declarative-XML parsers (acl.xml, indexer.xml, mview.xml --
    see each parser's own docstring for the fact shape it extracts from the
    returned root). Returns None for a missing or malformed file, same
    "doesn't exist / skip" handling every one of these parsers already used
    individually before this helper existed.
    """
    if not path.is_file():
        return None

    try:
        return etree.parse(str(path)).getroot()
    except etree.XMLSyntaxError:
        return None
