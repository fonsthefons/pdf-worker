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


TARGET = (
    " Write about {target} words: the original has {original}. Reach that length by "
    "saying each idea in fewer words, not by leaving ideas out."
)


class Target:
    """A chat whose system prompt names the length in words (set before each request)."""

    def __init__(self, chat):
        self.chat, self.target, self.original = chat, 0, 0

    def context_words(self):
        return self.chat.context_words()

    def __call__(self, system, user):
        extra = TARGET.format(target=self.target, original=self.original)
        return self.chat(system + extra, user)


class Used:
    """The chat, counting the models that answered (a pinned model falls back silently)."""

    def __init__(self, chat):
        self.chat, self.models = chat, {}

    def context_words(self):
        return self.chat.context_words()

    def __call__(self, system, user):
        text, model = self.chat(system, user)
        self.models[model] = self.models.get(model, 0) + 1
        return text, model


class Pieces:
    """A chat whose context holds only ``words`` of text: summarize cuts the part there."""

    def __init__(self, chat, words):
        self.chat, self.words = chat, words

    def context_words(self):
        return self.words

    def __call__(self, system, user):
        return self.chat(system, user)


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
    model = next((a[8:] for a in sys.argv[5:] if a.startswith("--model=")), MODEL)
    chat = Used(summ.ModelChat(model))
    used = chat.models
    print(f"model={model}")
    if variant == "C":
        chat = Skeleton(chat, "es")
    target = None
    if variant.startswith("E"):  # E[<words>]: the length named in words, pieces if given
        chat = target = Target(chat)
    if variant[0] in "DE" and variant[1:]:  # <words>: pieces of that size, joined, no merge
        chat = Pieces(chat, int(variant[1:]))
    ask = summ._Run.ask

    def logged(self, path, units, original, phrases, merge=False):
        if merge and variant[0] in "DE":
            return "\n\n".join(units)
        if target:
            target.original, target.target = original, round(original * self.percent / 100)
        answer = ask(self, path, units, original, phrases, merge)
        n = len(answer.split())
        print(f"  piece {original} -> {n} words ({100 * n / original:.0f}%)", flush=True)
        return answer

    summ._Run.ask = logged
    blocks_out = summ.summarize(
        outline, nodes, 0, chat, out / f"cache-{variant}.json", lang="es", detail="full",
        keep_bold=keep_bold, fresh=True,
    )
    text = "\n\n".join(getattr(b, "text", "") for b in blocks_out if getattr(b, "text", ""))
    (out / f"{variant}.txt").write_text(text, "utf-8")
    if variant == "C":
        (out / "C-ideas.txt").write_text("\n\n====\n\n".join(chat.ideas.values()), "utf-8")
    print(f"keep_bold={keep_bold} answered by: {used}")
    words = len(text.split())
    print(f"{variant}: {words} words = {100 * words / nodes[0].words:.0f}% of {nodes[0].words}")


main()
