"""Shared types for the document writers (Markdown, EPUB)."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Metadata:
    title: str
    author: str = ""
    language: str = "en"  # BCP 47 code, e.g. "es"


@dataclass
class WriteStats:
    headings: int = 0
    paragraphs: int = 0
    notes: int = 0
    chapters: int = 0
