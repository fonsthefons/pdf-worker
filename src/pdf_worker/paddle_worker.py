"""PaddleOCR-VL worker, run by the separate Paddle environment's Python.

It must not import pdf_worker (that package lives in the main environment): it only
needs PyMuPDF and PaddleOCR. It renders the requested pages, runs the PaddleOCR-VL
pipeline against an already running MLX-VLM server, and writes one JSON line per page:

    {"page": 3, "width": 1300, "height": 1850,
     "blocks": [{"label": "text", "bbox": [x0, y0, x1, y1], "text": "..."}]}

``width``/``height`` are the rendered image's pixels, the unit of the boxes.
"""

import argparse
import json
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pdf", required=True)
    parser.add_argument("--pages", required=True, help="Comma-separated 0-based indices.")
    parser.add_argument("--out", required=True, help="JSON lines output file.")
    parser.add_argument("--work", required=True, help="Folder for page images.")
    parser.add_argument("--server", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--dpi", type=int, default=200)
    args = parser.parse_args()

    import pymupdf
    from paddleocr import PaddleOCRVL

    pipeline = PaddleOCRVL(
        vl_rec_backend="mlx-vlm-server",
        vl_rec_server_url=args.server,
        vl_rec_api_model_name=args.model,
        # mlx_vlm.server fails on concurrent requests with differently sized crops
        # ("[broadcast_shapes] Shapes (8) and (2) cannot be broadcast").
        vl_rec_max_concurrency=1,
    )
    work = Path(args.work)
    work.mkdir(parents=True, exist_ok=True)
    pages = [int(p) for p in args.pages.split(",") if p]
    with pymupdf.open(args.pdf) as doc, open(args.out, "w", encoding="utf-8") as out:
        for done, index in enumerate(pages, start=1):
            image = work / f"page-{index}.png"
            doc.load_page(index).get_pixmap(dpi=args.dpi).save(image)
            blocks = []
            width = height = 0
            for result in pipeline.predict(str(image)):
                data = result.json.get("res", result.json)
                width, height = data.get("width", 0), data.get("height", 0)
                for block in data.get("parsing_res_list", []):
                    blocks.append(
                        {
                            "label": block.get("block_label", ""),
                            "bbox": block.get("block_bbox", []),
                            "text": block.get("block_content", "") or "",
                        }
                    )
            image.unlink(missing_ok=True)
            row = {"page": index, "width": width, "height": height, "blocks": blocks}
            out.write(json.dumps(row, ensure_ascii=False) + "\n")
            out.flush()
            print(f"paddle: page {done}/{len(pages)}", file=sys.stderr, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
