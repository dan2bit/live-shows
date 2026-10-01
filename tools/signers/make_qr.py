#!/usr/bin/env python3
"""Generate a QR-code SVG, optionally with a logo reserved in the center.

A QR code is a pure function of the encoded string plus the encoder
settings (error-correction level, quiet-zone width) - identical inputs
always produce an identical matrix, so both QR files this repo ships
(static/hat-playlist-qr.svg, static/redhat-bootlegs-qr.svg) are stored
outputs of this script, not hand-maintained. Regenerate only when the
encoded URL changes, and re-run the decode check below afterward.

Plain QR (no logo), error correction M:
    python3 tools/signers/make_qr.py \\
        "https://open.spotify.com/playlist/16iFg2ws9smr9vGVNaI3FK" \\
        static/hat-playlist-qr.svg

QR with a centered logo, error correction H (required for a logo overlay -
covering part of the code needs the recovery budget an overlay eats into):
    python3 tools/signers/make_qr.py \\
        "https://redhat-bootlegs.net" \\
        static/redhat-bootlegs-qr.svg \\
        --logo static/brand-hat.png --logo-width-modules 9

--logo-width-modules default (9, ~27% of a version-4 code's width, ~5% of
its area) was picked empirically, not from the ~30% theoretical ceiling for
error-correction level H: a sweep from 6-12 modules, rendered at 300/600/
1200px and decoded with two independent readers (OpenCV, zbar), passed
cleanly through 11 and failed at 12 on one reader at one resolution. 9
leaves real margin below that observed failure point rather than sitting
at the edge of it - decoder behavior wasn't perfectly monotonic with size,
so "still passes today" isn't a reason to push closer to the boundary.
"""
import argparse
import base64
import io
import sys

import segno
from PIL import Image


def build_plain(url, error):
    qr = segno.make(url, error=error, micro=False)
    buf = io.BytesIO()
    qr.save(buf, kind="svg", border=4, dark="#000", light="#fff",
            omitsize=True, xmldecl=False,
            title=f"QR code: {url}", desc=url)
    return buf.getvalue().decode("utf-8")


def build_with_logo(url, error, logo_path, logo_width_modules):
    qr = segno.make(url, error=error, micro=False)
    matrix = list(qr.matrix_iter(scale=1, border=0))
    n = len(matrix)
    border = 4
    size = n + 2 * border

    path_parts = []
    for y, row in enumerate(matrix):
        x = 0
        while x < n:
            if row[x]:
                x0 = x
                while x < n and row[x]:
                    x += 1
                path_parts.append(f"M{x0+border} {y+border}h{x-x0}v1h-{x-x0}z")
            else:
                x += 1
    module_path = "".join(path_parts)

    logo = Image.open(logo_path)
    bbox = logo.getbbox()  # tight crop to real content if the source has padding
    if bbox:
        pad = max(1, round(0.02 * max(logo.size)))
        l, t, r, b = bbox
        l = max(0, l - pad); t = max(0, t - pad)
        r = min(logo.width, r + pad); b = min(logo.height, b + pad)
        logo = logo.crop((l, t, r, b))
    aspect = logo.width / logo.height

    logo_w = logo_width_modules
    logo_h = logo_w / aspect
    cx = cy = size / 2
    logo_x, logo_y = cx - logo_w / 2, cy - logo_h / 2

    plate_margin = 1.0
    plate_w, plate_h = logo_w + 2 * plate_margin, logo_h + 2 * plate_margin
    plate_x, plate_y = cx - plate_w / 2, cy - plate_h / 2

    buf = io.BytesIO()
    logo.save(buf, format="PNG")
    logo_b64 = base64.b64encode(buf.getvalue()).decode("ascii")

    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}">\n'
        f'<title>QR code: {url}</title>\n'
        f'<desc>{url}</desc>\n'
        f'<rect width="{size}" height="{size}" fill="#fff"/>\n'
        f'<path fill="#000" d="{module_path}"/>\n'
        f'<rect x="{plate_x:.3f}" y="{plate_y:.3f}" width="{plate_w:.3f}" height="{plate_h:.3f}" '
        f'rx="1.2" ry="1.2" fill="#fff"/>\n'
        f'<image x="{logo_x:.3f}" y="{logo_y:.3f}" width="{logo_w:.3f}" height="{logo_h:.3f}" '
        f'href="data:image/png;base64,{logo_b64}"/>\n'
        f'</svg>'
    )


def decode_check(svg_path, expected_url):
    """Rasterize at a few sizes and confirm at least one of two independent
    decoders reads the intended URL at each size - catching a genuinely
    broken code (oversized logo, wrong URL: both decoders fail together)
    before it ships, without requiring unanimous agreement at every size.

    Requiring both was tried first and rejected: cv2's bundled detector
    intermittently misreads a cairosvg antialiased render at a non-integer
    module-to-pixel scale (a PLAIN QR, no logo, failed cv2 only at
    res=1200 - confirmed not a logo-size or code-path issue by rendering
    the identical bytes both from a file and from memory and finding cv2
    fails on both, pixel-for-pixel identical either way) while zbar reads
    the exact same pixels correctly. That is a narrow limitation of one
    test decoder, not evidence the code itself is bad - so this checks for
    at least one real reader succeeding, which is what "will this scan"
    actually needs.
    """
    try:
        import cairosvg
        import cv2
        import numpy as np
        from pyzbar.pyzbar import decode as zbar_decode
    except ImportError:
        print("(skipping decode check: cairosvg/opencv-python-headless/pyzbar not installed)",
              file=sys.stderr)
        return True
    ok = True
    for res in (300, 600, 1200):
        png_bytes = cairosvg.svg2png(url=svg_path, output_width=res, output_height=res)
        img = cv2.imdecode(np.frombuffer(png_bytes, dtype="uint8"), cv2.IMREAD_COLOR)
        cv2_val, _, _ = cv2.QRCodeDetector().detectAndDecode(img)
        z = zbar_decode(img)
        zbar_val = z[0].data.decode("utf-8") if z else None
        row_ok = (cv2_val == expected_url) or (zbar_val == expected_url)
        ok = ok and row_ok
        print(f"  res={res:>4}: cv2={'PASS' if cv2_val==expected_url else 'FAIL'} "
              f"zbar={'PASS' if zbar_val==expected_url else 'FAIL'}"
              f"{'' if row_ok else '  <- BOTH failed, this is a real problem'}")
    return ok


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("url")
    p.add_argument("out_svg")
    p.add_argument("--logo", help="path to a logo image; omit for a plain QR")
    p.add_argument("--logo-width-modules", type=float, default=9.0)
    p.add_argument("--error", choices=list("lmqh"), default=None,
                    help="error-correction level; defaults to m (plain) or h (--logo given)")
    p.add_argument("--no-check", action="store_true", help="skip the post-build decode check")
    args = p.parse_args()

    error = args.error or ("h" if args.logo else "m")
    if args.logo:
        svg = build_with_logo(args.url, error, args.logo, args.logo_width_modules)
    else:
        svg = build_plain(args.url, error)

    with open(args.out_svg, "w", encoding="utf-8") as f:
        f.write(svg)
    print(f"wrote {args.out_svg}")

    if not args.no_check:
        print("decode check:")
        if not decode_check(args.out_svg, args.url):
            sys.exit(f"decode check FAILED for {args.out_svg} - do not commit this file as-is")


if __name__ == "__main__":
    main()
