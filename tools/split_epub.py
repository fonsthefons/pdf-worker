"""Split an EPUB into one EPUB per top-level TOC entry, keeping the content as is.

Usage: split_epub.py BOOK.epub [OUT_DIR] [--series S] [--descriptions F.json] [--prefix P]
Parts without a --descriptions entry are described by their contents. A part whose first
page shows an image (its own cover page) gets that image as its cover.
Each part keeps the spine slice from its TOC entry up to the next one, the resources
those pages reference, and that entry's sub-TOC. Links into other parts will break.
"""

import argparse
import copy
import json
import os
import pathlib
import posixpath
import re
import tempfile
import uuid
import xml.etree.ElementTree as ET
import zipfile
from xml.sax.saxutils import escape

OPF = "{http://www.idpf.org/2007/opf}"
DC = "{http://purl.org/dc/elements/1.1/}"
NCX = "{http://www.daisy.org/z3986/2005/ncx/}"
for ns_prefix, uri in [("", OPF[1:-1]), ("dc", DC[1:-1]), ("opf", OPF[1:-1])]:
    ET.register_namespace(ns_prefix, uri)
REF = re.compile(rb"""(?:href|src)\s*=\s*["']([^"'#]+)|url\(\s*["']?([^"')#]+)""")


def split(path, out_dir, series=None, descriptions=None, prefix=None):
    z = zipfile.ZipFile(path)
    container = ET.fromstring(z.read("META-INF/container.xml"))
    opf_path = next(e.get("full-path") for e in container.iter() if e.get("full-path"))
    base = posixpath.dirname(opf_path)
    opf_root = ET.fromstring(z.read(opf_path))
    manifest = opf_root.find(f"{OPF}manifest")
    spine = opf_root.find(f"{OPF}spine")
    items = {i.get("id"): i for i in manifest}
    full = {i.get("id"): posixpath.join(base, i.get("href")) for i in manifest}
    by_full = {v: k for k, v in full.items()}
    order = [r.get("idref") for r in spine]
    spine_ids = set(order)
    ncx_id = spine.get("toc")
    ncx_path = full[ncx_id]
    ncx_root = ET.fromstring(z.read(ncx_path))
    nav_map = ncx_root.find(f"{NCX}navMap")
    tops = list(nav_map)
    if len(tops) == 1:  # a single wrapper entry around the real parts
        tops = tops[0].findall(f"{NCX}navPoint")
    starts = []
    for nav in tops:
        src = nav.find(f"{NCX}content").get("src").split("#")[0]
        starts.append(order.index(by_full[posixpath.join(posixpath.dirname(ncx_path), src)]))
    cover = next(
        (m.get("content") for m in opf_root.iter(f"{OPF}meta") if m.get("name") == "cover"), None
    )
    stem = prefix or os.path.splitext(os.path.basename(path))[0]
    title = opf_root.find(f"{OPF}metadata/{DC}title").text.strip()

    for n, (nav, start) in enumerate(zip(tops, starts, strict=True)):
        end = starts[n + 1] if n + 1 < len(starts) else len(order)
        # a part opening with its own cover page gets that image as its cover
        first = full[order[start]]
        img = re.search(rb'(?:xlink:href|src)="([^"]+\.(?:jpe?g|png))"', z.read(first))
        part_cover = img and by_full.get(
            posixpath.normpath(posixpath.join(posixpath.dirname(first), img.group(1).decode()))
        )
        part_cover = part_cover or (cover if cover in items else None)
        keep = set(order[start:end]) | {ncx_id} | ({part_cover} if part_cover else set())
        todo = list(keep)
        while todo:  # pull in everything the kept files reference (css, images, fonts)
            f = full[todo.pop()]
            if not items[by_full[f]].get("media-type", "").endswith(("html+xml", "css", "html")):
                continue
            for m in REF.finditer(z.read(f)):
                ref = (m.group(1) or m.group(2)).decode(errors="ignore")
                dep = by_full.get(posixpath.normpath(posixpath.join(posixpath.dirname(f), ref)))
                if dep and dep not in keep and dep not in spine_ids:  # not other parts' pages
                    keep.add(dep)
                    todo.append(dep)
        label = nav.find(f"{NCX}navLabel/{NCX}text").text.strip()
        write_part(
            z,
            opf_path,
            opf_root,
            ncx_path,
            ncx_root,
            nav,
            keep,
            full,
            label,
            n + 1,
            series or title,
            descriptions or {},
            part_cover,
            os.path.join(out_dir, f"{stem} - {label}.epub"),
        )
        print(f"{label}: {end - start} pages, {len(keep)} files")


# Label prefixes of front/back matter, left out of a part's contents.
# shortcut: Spanish labels only; extend when splitting books in other languages
NOT_CONTENTS = (
    "cubierta",
    "portada",
    "introducción",
    "autor",
    "sobre el autor",
    "nota",
    "bibliografía",
    "índice",
    "créditos",
    "sinopsis",
    "variantes",
    "abreviaturas",
)


def clean_metadata(opf_root, nav, label, index, series, descriptions, cover):
    """Fresh metadata for one part: its own title, id, contents and cover; the source's
    author, language, publisher and subjects; converter junk dropped."""
    meta = opf_root.find(f"{OPF}metadata")

    def texts(tag):
        return [e.text.strip() for e in meta.iter(f"{DC}{tag}") if e.text and e.text.strip()]

    old_id = next(iter(texts("identifier")), "")
    lines = [
        f"<dc:title>{escape(label)}</dc:title>",
        f'<dc:identifier id="{opf_root.get("unique-identifier")}" opf:scheme="uuid">'
        f"urn:uuid:{uuid.uuid5(uuid.NAMESPACE_URL, f'{old_id}#{label}')}</dc:identifier>",
    ]
    lines += [f'<dc:creator opf:role="aut">{escape(c)}</dc:creator>' for c in texts("creator")]
    for tag in ("language", "publisher", "subject"):
        for v in texts(tag):
            v = v.title() if tag == "publisher" and v.isupper() else v  # GREDOS -> Gredos
            lines.append(f"<dc:{tag}>{escape(v)}</dc:{tag}>")
    contents = [
        t.text.strip()
        for t in nav.findall(f"{NCX}navPoint/{NCX}navLabel/{NCX}text")
        if t.text
        and t.text.strip() != label
        and not t.text.strip().lower().startswith(NOT_CONTENTS)
    ]
    description = descriptions.get(label) or (contents and "Contiene: " + ", ".join(contents) + ".")
    if description:
        lines.append(f"<dc:description>{escape(description)}</dc:description>")
    lines += [
        f'<meta name="calibre:series" content="{escape(series, {chr(34): "&quot;"})}" />',
        f'<meta name="calibre:series_index" content="{index}" />',
    ]
    if cover:
        lines.append(f'<meta name="cover" content="{cover}" />')
    ns = f'xmlns:dc="{DC[1:-1]}" xmlns:opf="{OPF[1:-1]}"'
    return f"<metadata {ns}>\n    " + "\n    ".join(lines) + "\n  </metadata>"


def write_part(
    z,
    opf_path,
    opf_root,
    ncx_path,
    ncx_root,
    nav,
    keep,
    full,
    label,
    index,
    series,
    descriptions,
    cover,
    out,
):
    opf = ET.fromstring(ET.tostring(opf_root))
    for parent in (opf.find(f"{OPF}manifest"), opf.find(f"{OPF}spine")):
        for e in list(parent):
            if (e.get("id") or e.get("idref")) not in keep:
                parent.remove(e)
    guide = opf.find(f"{OPF}guide")
    kept_hrefs = {posixpath.relpath(full[k], posixpath.dirname(opf_path)) for k in keep}
    if guide is not None:
        for e in list(guide):
            if e.get("href", "").split("#")[0] not in kept_hrefs:
                guide.remove(e)
    ET.register_namespace("", NCX[1:-1])
    ncx = ET.fromstring(ET.tostring(ncx_root))
    doc_title = ncx.find(f"{NCX}docTitle/{NCX}text")
    if doc_title is not None:
        doc_title.text = label
    nav_map = ncx.find(f"{NCX}navMap")
    for e in list(nav_map):
        nav_map.remove(e)
    nav_map.extend(ET.fromstring(ET.tostring(nav)).findall(f"{NCX}navPoint") or [nav])
    ET.register_namespace("", OPF[1:-1])
    opf_bytes = re.sub(
        rb"<metadata.*?</metadata>|<metadata[^>]*/>",
        clean_metadata(opf_root, nav, label, index, series, descriptions, cover).encode(),
        ET.tostring(opf, xml_declaration=True, encoding="utf-8"),
        count=1,
        flags=re.S,
    )
    ET.register_namespace("", NCX[1:-1])
    ncx_bytes = ET.tostring(ncx, xml_declaration=True, encoding="utf-8")
    keep_files = {full[k] for k in keep}

    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(out), suffix=".epub.tmp")
    os.close(fd)
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as o:
        o.writestr(zipfile.ZipInfo("mimetype"), b"application/epub+zip", zipfile.ZIP_STORED)
        for info in z.infolist():
            name = info.filename
            if name == "mimetype":
                continue
            if name == opf_path:
                o.writestr(name, opf_bytes)
            elif name == ncx_path:
                o.writestr(name, ncx_bytes)
            elif name.startswith("META-INF/") or name in keep_files:
                o.writestr(copy.copy(info), z.read(name))  # writestr mutates the ZipInfo's offset
    os.replace(tmp, out)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("book")
    ap.add_argument("out_dir", nargs="?", help="default: the book's folder")
    ap.add_argument("--series", help="the parts' series name (default: the book's title)")
    ap.add_argument("--descriptions", type=pathlib.Path, help="JSON: part TOC label -> description")
    ap.add_argument("--prefix", help="file names are 'PREFIX - LABEL.epub' (default: book name)")
    a = ap.parse_args()
    split(
        a.book,
        a.out_dir or os.path.dirname(os.path.abspath(a.book)),
        a.series,
        a.descriptions and json.loads(a.descriptions.read_text("utf-8")),
        a.prefix,
    )
