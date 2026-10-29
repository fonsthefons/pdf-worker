"""PaddleOCR-VL worker, run by the separate Paddle environment's Python.

It must not import pdf_worker (that package lives in the main environment): it only
needs PyMuPDF and PaddleOCR. It renders the requested pages, runs the PaddleOCR-VL
pipeline against an already running MLX-VLM server, and writes one JSON line per page:

    {"page": 3, "width": 1300, "height": 1850,
     "blocks": [{"label": "text", "bbox": [x0, y0, x1, y1], "text": "..."}]}

``width``/``height`` are the rendered image's pixels, the unit of the boxes.

With ``--layout-only`` it runs the pipeline's layout model alone (no server, no text),
with PaddleOCR-VL-1.5's settings, on pages rendered at 150 dpi (the model resizes them to
800x800 anyway); blocks are ``{"label", "score", "bbox"}``.
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
    parser.add_argument("--layout-only", action="store_true")
    parser.add_argument("--server")
    parser.add_argument("--model")
    parser.add_argument("--dpi", type=int)
    args = parser.parse_args()
    if not args.layout_only and not (args.server and args.model):
        parser.error("--server and --model are needed without --layout-only")

    import pymupdf

    if args.layout_only:
        from paddleocr import LayoutDetection

        model = LayoutDetection(model_name="PP-DocLayoutV3", threshold=0.3, layout_nms=True)
        read = _layout_reader(model)
    else:
        from paddleocr import PaddleOCRVL

        pipeline = PaddleOCRVL(
            vl_rec_backend="mlx-vlm-server",
            vl_rec_server_url=args.server,
            vl_rec_api_model_name=args.model,
            # mlx_vlm.server fails on concurrent requests with differently sized crops
            # ("[broadcast_shapes] Shapes (8) and (2) cannot be broadcast").
            vl_rec_max_concurrency=1,
        )
        read = _pipeline_reader(pipeline)
    dpi = args.dpi or (150 if args.layout_only else 200)
    work = Path(args.work)
    work.mkdir(parents=True, exist_ok=True)
    pages = [int(p) for p in args.pages.split(",") if p]
    with pymupdf.open(args.pdf) as doc, open(args.out, "w", encoding="utf-8") as out:
        for done, index in enumerate(pages, start=1):
            image = work / f"page-{index}.png"
            pixmap = doc.load_page(index).get_pixmap(dpi=dpi, annots=False)
            pixmap.save(image)
            width, height, blocks = read(image, pixmap)
            image.unlink(missing_ok=True)
            row = {"page": index, "width": width, "height": height, "blocks": blocks}
            out.write(json.dumps(row, ensure_ascii=False) + "\n")
            out.flush()
            print(f"paddle: page {done}/{len(pages)}", file=sys.stderr, flush=True)
    return 0


def _pipeline_reader(pipeline):
    def read(image, pixmap):
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
        return width, height, blocks

    return read


def _layout_reader(model):
    def read(image, pixmap):
        blocks = [
            {
                "label": box["label"],
                "score": round(float(box["score"]), 3),
                "bbox": [round(float(c), 1) for c in box["coordinate"]],
            }
            for result in model.predict(str(image), batch_size=1)
            for box in result.json.get("res", result.json).get("boxes", [])
        ]
        # The result has no page size: the image's is the unit of the boxes.
        return pixmap.width, pixmap.height, blocks

    return read


if __name__ == "__main__":
    sys.exit(main())
