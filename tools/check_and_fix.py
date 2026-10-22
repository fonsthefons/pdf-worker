"""Check EPUBs for the OCF mimetype entry and repack the ones that get it wrong.

Usage: check_and_fix.py BOOK.epub [BOOK.epub ...] [--check]
Books that break the rule (see `pdf_worker.epub_mimetype`) are rewritten in place with a
correct `mimetype` entry first and every other entry copied unchanged.
"""

import argparse
import sys
import zipfile

from pdf_worker.epub_mimetype import fix, problem

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("books", nargs="+")
    ap.add_argument("--check", action="store_true", help="only report, don't fix")
    args = ap.parse_args()
    bad = 0
    for book in args.books:
        try:
            why = problem(book)
        except (OSError, zipfile.BadZipFile) as e:
            print(f"ERROR  {book}: {e}")
            bad += 1
            continue
        if why is None:
            print(f"ok     {book}")
        elif args.check or why == "not a ZIP file":
            print(f"BAD    {book}: {why}")
            bad += 1
        else:
            fix(book)
            assert problem(book) is None
            print(f"fixed  {book}: {why}")
    sys.exit(1 if bad else 0)
