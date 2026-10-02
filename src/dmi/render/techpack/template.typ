// The tech pack layout. All content comes from the view built in Python
// (dmi.render.techpack.view); this file only lays it out.
#let doc = json(bytes(sys.inputs.at("view")))
#set document(title: doc.cover.title, date: none)
#set page(paper: "a4", margin: (x: 1.4cm, y: 1.6cm),
  footer: context [#set text(8pt, fill: luma(110)); #doc.cover.title #h(1fr) page #counter(page).display() of #counter(page).final().first()])
#set text(font: "Libertinus Serif", size: 9pt)
#show heading.where(level: 1): it => block(above: 1.2em, below: 0.6em, text(13pt, weight: "bold", it.body))

#let gapfill = rgb("#FFF1B8")
#let cellc(c) = if c.gap { table.cell(fill: gapfill)[#text(fill: rgb("#7A5B00"))[#c.text]] } else { [#c.text] }

#let render-table(b) = {
  let n = b.columns.len()
  let widths = if b.widths == none { (auto,) * n } else {
    b.widths.map(w => if w == "auto" { auto } else { float(w.trim("fr")) * 1fr })
  }
  let has-header = b.columns.any(c => c != "")
  table(
    columns: widths, stroke: 0.4pt + luma(180), inset: 4pt,
    ..if has-header { (table.header(..b.columns.map(c => text(weight: "bold")[#c])),) } else { () },
    ..b.rows.flatten().map(cellc),
  )
  v(0.4em)
}

#let render-images(b) = grid(columns: (1fr, 1fr, 1fr), gutter: 8pt,
  ..b.items.map(it => block(breakable: false)[
    #if it.path == none {
      rect(width: 100%, height: 3.2cm, stroke: 0.5pt + luma(150))[#align(center + horizon, text(7pt, fill: luma(100))[image #it.ref])]
    } else { image(it.path, width: 100%, height: 4.2cm, fit: "contain") }
    #text(7pt, fill: luma(80))[#it.caption]
  ]))

// Cover
#align(left)[
  #text(18pt, weight: "bold")[#doc.cover.title]
  #v(2pt)
  #text(10pt, fill: luma(90))[Tech pack]
]
#v(0.8em)
#table(columns: (auto, 1fr), stroke: none, inset: 3pt,
  ..doc.cover.rows.flatten().map(x => [#x]))

#for s in doc.sections {
  heading(level: 1, s.title)
  for b in s.blocks {
    if b.kind == "table" { render-table(b) }
    else if b.kind == "images" { render-images(b) }
    else if b.text != "" { par[#b.text] }
  }
}
