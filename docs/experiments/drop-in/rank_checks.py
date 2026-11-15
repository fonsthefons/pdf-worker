"""Counts behind the ranking of docs/results.md (drop-in experiment, step S4), on a
`tools/quality.py build` folder; nothing is converted.

  rank_checks.py headings DIR...   quality.json's missed and wrong headings, main and sub apart
  rank_checks.py loops DIR         made-up loops in the folder's *.md
  rank_checks.py refs DIR...       bracketed margin references in platon_bad.md and dialogos.md
  rank_checks.py selftest

Main heading (what a contents table lists: parts, chapters, front and back matter), by a
rough rule: the title starts with a part or chapter word, or is in capitals, and does not
start with an arabic number or a letter item ("4. ", "a) "). Everything else is a subheading.
Loop: one 4-word sequence at least 4 times within 50 words of a paragraph; it also catches
real repetition ("el amor de la patria, el amor de la humanidad..."), so read each hit.
"""

import json
import re
import sys
from pathlib import Path

_MAIN = re.compile(
    r"(?i)^((primera|segunda|te?rcera|cuarta|quinta)\s+parte|parte\b|cap[ií]tulos?\b"
    r"|ap[eé]ndices?\b|pr[oó]logo|introducci[oó]n|[ií]ndice|ep[ií]logo|conclusi[oó]n"
    r"|bibliograf[ií]a\b)"
)
_ITEM = re.compile(r"^\s*(\d+[.)]|[a-z]\s*\.?\)|\d+\s)")


def is_main(title: str) -> bool:
    if _ITEM.match(title):
        return False
    letters = [c for c in title if c.isalpha()]
    capitals = len(letters) >= 4 and sum(c.isupper() for c in letters) >= 0.8 * len(letters)
    return bool(_MAIN.match(title.strip())) or capitals


def loop_words(paragraph: str) -> tuple[int, str]:
    """Words inside loops of the paragraph (0 when none) and the loop's first words."""
    words = re.findall(r"\w+", paragraph.lower())
    seen: dict[tuple, list[int]] = {}
    hit: set[int] = set()
    for i in range(len(words) - 3):
        places = seen.setdefault(tuple(words[i : i + 4]), [])
        places.append(i)
        if len(places) >= 4 and i - places[-4] <= 50:
            hit.update(range(places[-4], i + 4))
    return len(hit), " ".join(words[min(hit) : min(hit) + 16]) if hit else ""


def headings(folders: list[str]) -> None:
    for folder in folders:
        books = json.loads((Path(folder) / "quality.json").read_text(encoding="utf-8"))["books"]
        for label, book in books.items():
            scores = book.get("headings")
            if not scores:
                continue
            print(f"{Path(folder).name} {label}: reference {scores['ref']}, ours {scores['ours']}")
            for kind in ("missed", "wrong"):
                mains = [title for title in scores[kind] if is_main(title)]
                print(f"  {kind} {len(scores[kind])}: main {len(mains)} {mains}")


def loops(folder: str) -> None:
    for md in sorted(Path(folder).glob("*.md")):
        if md.name == "report.md":
            continue
        for number, line in enumerate(md.read_text(encoding="utf-8").splitlines(), 1):
            count, start = (0, "") if line.startswith("|") else loop_words(line)  # not tables
            if count:
                print(f"{md.stem} line {number}: {count} words: {start}")


def refs(folders: list[str]) -> None:
    for folder in folders:
        for label in ("platon_bad", "dialogos"):
            text = (Path(folder) / f"{label}.md").read_text(encoding="utf-8")
            print(Path(folder).name, label, len(re.findall(r"\[\d{1,3}[a-e]\\?\]", text)))


def selftest() -> None:
    assert is_main("CUARTA PARTE KANT") and is_main("Capítulo VIII")
    assert is_main("KANT.—I: VIDA Y ESCRITOS")
    assert not is_main("4. Montesquieu") and not is_main("a).- Fe y palabra")
    assert not is_main("Juicios") and not is_main("1. PRIMEROS AÑOS DE SÓCRATES")
    assert loop_words("la p y se deti a la mas se cima en " * 4)[0] > 20
    assert loop_words("uno dos tres cuatro cinco seis siete ocho nueve diez")[0] == 0
    print("ok")


if __name__ == "__main__":
    command, rest = sys.argv[1], sys.argv[2:]
    if command == "headings":
        headings(rest)
    elif command == "loops":
        loops(rest[0])
    elif command == "refs":
        refs(rest)
    else:
        selftest()
