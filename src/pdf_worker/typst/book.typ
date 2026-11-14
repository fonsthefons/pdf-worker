// pdf-worker's rules for a book PDF (pdf_worker.typst_export), set right after Pandoc's
// `#show: doc => conf(...)`, whose own page rules would override them. sys.inputs:
// title, author, lang, notes ("page" or "end"), notes-title, cover ("" or a picture).
#let inputs = sys.inputs
#set document(title: inputs.title)
#set document(author: inputs.author) if inputs.author != ""
#set page(paper: "a5", margin: 42pt, numbering: "1")
#set text(lang: inputs.lang, font: "New Computer Modern")
#set par(justify: true)

// A margin reference ("34b"): in the right margin, level with its line; estimated
// ones ("~34c") pink, as in the EPUB.
#let mref(label) = place(left, dx: 100% + 6pt, text(
  size: 7.5pt,
  weight: "bold",
  fill: if label.starts-with("~") { rgb("#d81b60") } else { rgb("#2e7d32") },
  label,
))

// Notes at the end: each footnote leaves its number in the text and its body for the
// notes section after the book.
#let endnotes = state("endnotes", ())
#show footnote: it => if inputs.notes == "end" {
  endnotes.update(notes => notes + (it.body,))
  context {
    let n = str(endnotes.get().len())
    [#link(label("note-" + n), super(n))#label("ref-" + n)]
  }
} else { it }
// Typst still gathers the footnotes for the page's foot: leave them out there.
#show footnote.entry: it => if inputs.notes != "end" { it }
#set footnote.entry(separator: none) if inputs.notes == "end"
#show: body => {
  body
  context {
    let notes = endnotes.final()
    if notes.len() > 0 {
      pagebreak(weak: true)
      heading(level: 1, inputs.notes-title)
      set text(size: 0.9em)
      for (i, note) in notes.enumerate() {
        let n = str(i + 1)
        [#block[#link(label("ref-" + n))[#super(n)~↑]~#note]#label("note-" + n)]
      }
    }
  }
}

#if inputs.cover != "" {
  page(margin: 0pt, numbering: none, image(inputs.cover, width: 100%, height: 100%))
}
// The contents, on its own page, when the book has headings.
#context if query(heading).len() > 0 {
  outline()
  pagebreak(weak: true)
}
