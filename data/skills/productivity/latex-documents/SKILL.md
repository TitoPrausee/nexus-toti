---
name: latex-documents
description: Generate professional German academic/scientific documents using LaTeX (KOMA-Script scrartcl), compile to PDF. Color-coded priority boxes, proper German typesetting, and compilation workflow.
tags: [latex, pdf, document, german, academic]
---

# LaTeX Document Generation

Generate professional German academic/scientific documents using LaTeX, compile to PDF.

## When to Use
- Creating specification documents, reports, analyses, or overview documents
- User asks for professional PDF output from structured data
- German-language academic or university documents

## Prerequisites
- `pdflatex` must be installed (check with `which pdflatex`)
- If missing: `apt-get update && apt-get install -y texlive-latex-recommended texlive-latex-extra texlive-lang-german texlive-fonts-recommended`

## Template: scrartcl (KOMA-Script Article)

Use `\documentclass[12pt,a4paper]{scrartcl}` for German professional documents. This provides better typography than `article`.

### Essential Packages
```latex
\usepackage[utf8]{inputenc}
\usepackage[T1]{fontenc}
\usepackage[ngerman]{babel}
\usepackage{geometry}
\geometry{margin=2.5cm}
\usepackage{tcolorbox}
\tcbuselibrary{skins}
\usepackage{tabularx}
\usepackage{booktabs}
\usepackage{enumitem}
\usepackage{hyperref}
\usepackage{xcolor}
```

### Color-Coded Priority Boxes
```latex
\definecolor{highred}{RGB}{220,50,50}
\definecolor{medorange}{RGB}{230,150,30}
\definecolor{lowgray}{RGB}{150,150,150}
\definecolor{fsuteal}{RGB}{0,128,144}

\newtcolorbox{highbox}{colback=highred!10,colframe=highred,title=\textbf{HIGH Priorit\"at}}
\newtcolorbox{medbox}{colback=medorange!10,colframe=medorange,title=\textbf{MEDIUM Priorit\"at}}
\newtcolorbox{lowbox}{colback=lowgray!10,colframe=lowgray,title=\textbf{LOW Priorit\"at}}
\newtcolorbox{riskbox}[1][]{colback=highred!10,colframe=highred,arc=2mm,title={#1}}
\newtcolorbox{phasebox}[1][]={colback=fsuteal!10,colframe=fsuteal,arc=2mm,title={#1}}
```

### German Umlauts in LaTeX
Use `\"a` for ä, `\"o` for ö, `\"u` for ü, `\"A` for Ä, `\"O` for Ö, `\"U` for Ü, `\ss` for ß.
Quote marks: `\glqq` for „ and `\grqq` for ".

## Compilation Workflow
1. Write `.tex` file with `write_file`
2. Compile: `cd /path && pdflatex -interaction=nonstopmode filename.tex`
3. Always run **twice** for correct table of contents (TOC) and cross-references
4. Output: `filename.pdf`

```bash
cd /path/to/dir && pdflatex -interaction=nonstopmode doc.tex && pdflatex -interaction=nonstopmode doc.tex
```

## Reusable Patterns

### TikZ Timeline Diagram (pgfplots)
For phased preparation timelines (project phases, training weeks, etc.):
```latex
\usepackage{tikz}
\usepackage{pgfplots}
\pgfplotsset{compat=1.18}
% In the document body:
\begin{tikzpicture}
  \begin{axis}[
    x=0.02\textwidth, y=50pt,
    xlabel={Phase}, xlabel style={font=\small},
    xmin=0.5, xmax=4.5, ymin=-0.5, ymax=3.8,
    xtick={1,2,3,4},
    xticklabels={Phase 1, Phase 2, Phase 3, Phase 4},
    ytick=\empty, axis lines=left,
    axis line style={-stealth, thick},
    width=\textwidth, height=5.5cm, clip=false,
  ]
  \node[fill=color1!20, draw=color1, rounded corners,
    minimum width=2.2cm, minimum height=1.2cm,
    align=center, font=\footnotesize\bfseries]
    at (axis cs:1, 3) {Label A};
  % ... more nodes, draw arrows between them
  \draw[-stealth, thick, gray] (axis cs:1.5, 3) -- (axis cs:2.0, 2.5);
  \end{axis}
\end{tikzpicture}
```

### Color-Coded Comparison Tables
For decision matrices comparing two options across criteria, use `\textcolor{highred}{Bad}` vs `\textcolor{succgreen}{Good}` inline coloring with a defined green:
```latex
\definecolor{succgreen}{RGB}{50,150,70}
% Then in tabularx: \textcolor{succgreen}{Ja} vs \textcolor{highred}{Nein}
```

### Priority-tiered Checklists
For equipment/requirement lists split into HIGH/MEDIUM/LOW, use three separate `tabularx` tables each with their own priority level, color-coded with `highbox`, `medbox`, `lowbox` tcolorboxes.

## Tips
- For tables with wrapped text, use `tabularx` with `\textwidth` and `X` columns
- For professional tables, use `\toprule`, `\midrule`, `\bottomrule` from `booktabs`
- `\newpage` before sections for clean TOC generation
- `\cellcolor{color!20}` for highlighted table cells
- Use `\normalfont` inside tcolorbox titles when mixing bold with normal text
- TikZ diagrams with pgfplots nodes work well for timelines — keep node content short and use `rounded corners`
- `.aux`, `.log`, `.out`, `.toc` files are build artifacts — add to `.gitignore`