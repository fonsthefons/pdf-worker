"""Shared types for the document writers (Markdown, EPUB)."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Metadata:
    title: str
    author: str = ""
    language: str = "en"  # BCP 47 code, e.g. "es"
    translator: str = ""


@dataclass
class WriteStats:
    headings: int = 0
    paragraphs: int = 0
    notes: int = 0
    glosses: int = 0
    images: int = 0
    tables: int = 0
    chapters: int = 0
    margin_refs: int = 0  # section numbers from the margin ("22b")
