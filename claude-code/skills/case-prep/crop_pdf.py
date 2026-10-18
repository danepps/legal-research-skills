# /// script
# dependencies = ["pymupdf>=1.24"]
# ///
"""
Crop a PDF's margins for comfortable reading on the reMarkable.

Shrinks every page's cropbox to the document-wide content bounding box
(text, images, line art) plus a small padding. One shared box keeps the
zoom level constant across pages. Display-only: page content is untouched.

Usage:
    uv run crop_pdf.py input.pdf              # writes input.pdf in place
    uv run crop_pdf.py input.pdf -o out.pdf   # writes to out.pdf

Exits nonzero (leaving files untouched) if no plausible content box is
found, so callers can fall back to the uncropped original.
"""

import argparse
import sys

import fitz  # pymupdf


def content_box(doc, padding=12, dpi=36):
    """
    Bounding box of visible ink across all pages, found by rendering each
    page at low resolution and scanning pixels. Object metadata (text or
    drawing bboxes) lies too often — invisible clip paths and white fills
    can extend to the page edges.
    """
    # Map near-white (>=250) to 0xff so C-level find/rfind can locate ink.
    table = bytes(0xFF if v >= 250 else 0x00 for v in range(256))
    scale = 72.0 / dpi
    union = None
    for page in doc:
        try:
            pix = page.get_pixmap(dpi=dpi, colorspace=fitz.csGRAY)
        except Exception:
            continue
        data = pix.samples.translate(table)
        x0 = y0 = None
        x1 = y1 = -1
        for row_i in range(pix.height):
            row = data[row_i * pix.stride : row_i * pix.stride + pix.width]
            left = row.find(0)
            if left == -1:
                continue
            right = row.rfind(0)
            if y0 is None:
                y0 = row_i
            y1 = row_i
            x0 = left if x0 is None else min(x0, left)
            x1 = max(x1, right)
        if y0 is None:
            continue
        r = fitz.Rect(x0 * scale, y0 * scale, (x1 + 1) * scale, (y1 + 1) * scale)
        r += fitz.Rect(page.rect.x0, page.rect.y0, page.rect.x0, page.rect.y0)
        union = r if union is None else union | r
    if union is None:
        return None
    union.x0 -= padding
    union.y0 -= padding
    union.x1 += padding
    union.y1 += padding
    return union


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("input")
    ap.add_argument("-o", "--output", help="output path (default: in place)")
    ap.add_argument("--padding", type=float, default=12, help="points of margin to keep")
    args = ap.parse_args()

    doc = fitz.open(args.input)
    box = content_box(doc, padding=args.padding)
    if box is None or box.width < 200 or box.height < 200:
        print(f"no plausible content box found in {args.input}; not cropping", file=sys.stderr)
        sys.exit(1)

    for page in doc:
        if page.rotation:
            continue  # rotated pages: bbox coords wouldn't line up
        try:
            page.set_cropbox(box & page.mediabox)
        except Exception:
            continue

    out = args.output or args.input
    first = doc[0]
    summary = (
        f"cropped {args.input} -> {out}: page 1 view "
        f"{first.mediabox.width:.0f}x{first.mediabox.height:.0f} -> "
        f"{first.rect.width:.0f}x{first.rect.height:.0f} pts"
    )
    # tobytes + write (not doc.save) so in-place output works: PyMuPDF
    # forbids a non-incremental save over the file it has open.
    data = doc.tobytes(garbage=3, deflate=True)
    doc.close()
    with open(out, "wb") as f:
        f.write(data)
    print(summary)


if __name__ == "__main__":
    main()
