"""SYNTHETIC PDF fixtures for the Game Manual Manager tests: valid, multi-page PDFs with real extractable text,
written from raw PDF syntax (no PDF library needed). They are not game manuals and are never evidence."""

from __future__ import annotations


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def make_pdf(pages: list[str]) -> bytes:
    """A PDF with one page per string; each line of a string is a text line on that page."""
    objects: list[bytes] = []
    font_id = 3
    page_ids = [4 + 2 * i for i in range(len(pages))]
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    kids = " ".join(f"{pid} 0 R" for pid in page_ids)
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>".encode())
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    for i, text in enumerate(pages):
        lines = text.split("\n")
        stream = "BT /F1 11 Tf 14 TL 50 760 Td " + " ".join(f"({_escape(line)}) Tj T*" for line in lines) + " ET"
        content = stream.encode("latin-1")
        objects.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 {font_id} "
                       f"0 R >> >> /Contents {page_ids[i] + 1} 0 R >>".encode())
        objects.append(b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream")
    out = bytearray(b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


def manual_pages(season: int = 2027, game: str = "SYNTHETICA") -> list[str]:
    """A SYNTHETIC miniature 'manual' exercising every extraction rule."""
    return [
        f"{season} FIRST Robotics Competition {game}\nGame Manual\nRevision 1.0\nJanuary 6, {season}",
        "5 ARENA\n5.1 Overview\nThe ARENA includes the FIELD and the scoring elements.",
        "6 MATCH Play\n6.1 Match periods\nThe AUTO period lasts 15 seconds.\nThe TELEOP period lasts 2 minutes and "
        "15 seconds.",
        "6.2 Scoring\nCORAL in the trough: 3 points\nALGAE in the net: 4 points\nLEAVE: 2 points\nThe ENDGAME begins "
        "with 20 seconds remaining.",
        "6.3 Ranking Points\nA team earns 3 Ranking Points for a win.\nThe AUTO RP is earned when every robot leaves.",
        "11 Tournaments\n11.1 Alliance Selection\nEight (8) ALLIANCES are formed in Alliance Selection.\n11.2 "
        "Playoffs\nThe playoff tournament is double-elimination with Finals best-of-three.",
    ]
