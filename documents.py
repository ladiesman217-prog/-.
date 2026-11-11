"""Read text paragraphs from a Microsoft Word .docx file using Python stdlib."""
from xml.etree import ElementTree
from zipfile import ZipFile
from io import BytesIO


WORD_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def extract_docx_text(content: bytes) -> str:
    with ZipFile(BytesIO(content)) as archive:
        xml_content = archive.read("word/document.xml")
    root = ElementTree.fromstring(xml_content)
    paragraphs = []
    for paragraph in root.iter(f"{WORD_NS}p"):
        text = "".join(node.text or "" for node in paragraph.iter(f"{WORD_NS}t")).strip()
        if text:
            paragraphs.append(text)
    return "\n".join(paragraphs)
