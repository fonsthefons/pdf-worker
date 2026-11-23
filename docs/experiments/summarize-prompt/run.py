"""Summarize prompt experiment: argv VARIANT(B|C|source) BLOCKS SECTION OUT_DIR [--no-bold].

B: a SYSTEM prompt that keeps main ideas and drops glosses, lists, supporting quotes.
C: B's prompt, after a first request that lists the part's key ideas as a skeleton.
source: write the section's own text (no requests).
Model pinned; --detail full --keep-bold; nothing written to the book's cache.
"""

import sys
from pathlib import Path

from pdf_worker import summarize as summ

MODEL = "nvidia/nemotron-3.5-super-vl:free"

SYSTEM_B = (
    "You write a faithful summary of one part of an academic or religious text. Use only "
    "what the text says, no outside knowledge. Keep the main ideas: the part's thesis, each "
    "step of its argument, key definitions and distinctions, and its conclusions. Keep who "
    "holds each main idea: tell the author's own views apart from those of anyone quoted "
    "(a Father of the Church, a Pope, a philosopher, Scripture). Quote only a sentence that "
    "carries a thesis; give another quotation's point in a few words, or leave it out. "
    "Leave out explanations of metaphors, lists of examples or items (say what they have "
    "in common instead), supporting quotations, digressions, repetition and restatements "
    "of a point already made. Keep technical and doctrinal terms and Latin or Greek terms "
    "as the text has them. Aim for about {percent}% of the original. Write prose "
    "paragraphs only: no headings, no lists, no Markdown, no preamble. Write in the "
    "language with the code '{lang}'."
)
IDEAS = (
    "List the main ideas of one part of an academic or religious text, in the text's "
    "order: its thesis, each step of its argument, key definitions and distinctions, and "
    "its conclusions. Go through the whole text: every section of the argument gets at "
    "least one line, including a section made mostly of quotations, where the line says "
    "what the quoted author argues and how the text uses it. One short line per idea, "
    "saying who holds it when it is not the author. Leave out examples, illustrations and "
    "restatements. Use only what the text says. Write in the language with the code "
    "'{lang}'. Write the list only, no preamble."
)
SKELETON = (
    "\n\nThe key ideas of this part, the summary's skeleton: cover each, in this order, "
    "taking from the text what each needs to be understood.\n\n{ideas}"
)


class Skeleton:
    """A chat that first asks for the part's key ideas, then writes from them."""

    def __init__(self, chat, lang):
        self.chat, self.lang, self.ideas = chat, lang, {}

    def context_words(self):
        return self.chat.context_words()

    def __call__(self, system, user):
        text = user.split("\n---\n\n", 1)[-1].split("\n\nYour summary:\n\n", 1)[0]
        if text not in self.ideas:
            self.ideas[text], _ = self.chat(IDEAS.format(lang=self.lang), user)
        return self.chat(system, user + SKELETON.format(ideas=self.ideas[text]))


def main():
    variant, blocks, section, out = sys.argv[1:5]
    keep_bold = "--no-bold" not in sys.argv[5:]
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    outline = summ.load_outline(blocks)
    nodes = summ.select(outline, [section])
    if variant == "source":
        units = summ._units(nodes[0], [])
        (out / "source.txt").write_text("\n\n".join(summ.plain(u) for u in units), "utf-8")
        return
    summ.SYSTEM = SYSTEM_B
    chat = summ.ModelChat(MODEL)
    if variant == "C":
        chat = Skeleton(chat, "es")
    blocks_out = summ.summarize(
        outline, nodes, 0, chat, out / f"cache-{variant}.json", lang="es", detail="full",
        keep_bold=keep_bold, fresh=True,
    )
    text = "\n\n".join(getattr(b, "text", "") for b in blocks_out if getattr(b, "text", ""))
    (out / f"{variant}.txt").write_text(text, "utf-8")
    if variant == "C":
        (out / "C-ideas.txt").write_text("\n\n====\n\n".join(chat.ideas.values()), "utf-8")
    print(f"keep_bold={keep_bold}")
    words = len(text.split())
    print(f"{variant}: {words} words = {100 * words / nodes[0].words:.0f}% of {nodes[0].words}")


main()
