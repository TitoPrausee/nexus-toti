---
name: beamer-tikz-guide
description: Create interactive presentation-style PDFs using LaTeX Beamer + TikZ illustrations. Use when you need visual documentation with diagrams, but don't have access to screenshot actual UIs. Replaces screenshots with hand-crafted SVG-quality vector illustrations.
version: 1.0.0
---

# Beamer TikZ Guide — Interactive Visual Documentation

When you need to explain a UI/tool/workflow but can't take screenshots (no access, NDA, or it doesn't exist yet), use **Beamer + TikZ** to create a presentation-quality PDF with vector illustrations instead.

## When to Use

- Explaining a tool/UI you can't screenshot
- Tutorial/guide documents that need visual diagrams
- Interactive PDFs with clickable navigation (hyperref)
- Any "how-to" doc that needs more than text

## Architecture

```
\documentclass[aspectratio=169, 12pt]{beamer}  % 16:9 widescreen
\usepackage{tikz}                               % Vector illustrations
\usepackage{hyperref}                            % Clickable links/nav
\usepackage{fontawesome5}                        % Icons (needs texlive-fonts-extra)
\usetikzlibrary{arrows.meta, positioning, calc, shapes.geometric, fit, backgrounds}
```

### Required Packages

```bash
sudo apt-get install -y texlive-full texlive-fonts-extra
# OR minimal:
sudo apt-get install -y texlive-latex-extra texlive-fonts-extra
```

## Design System (Dark Theme)

```latex
\definecolor{bg}{HTML}{0a0a0a}
\definecolor{surface}{HTML}{111113}
\definecolor{surface2}{HTML}{1c1c1e}
\definecolor{accent}{HTML}{0a84ff}
\definecolor{purple}{HTML}{5e5ce6}
\definecolor{pink}{HTML}{bf5af2}
\definecolor{green}{HTML}{30d158}
\definecolor{red}{HTML}{ff375f}
\definecolor{orange}{HTML}{ff9f0a}

\setbeamercolor{background canvas}{bg=bg}
\setbeamercolor{normal text}{fg=text1}
\setbeamertemplate{navigation symbols}{}  % Hide default nav
\setbeamertemplate{footline}{}            % Hide footer
```

## Key Patterns

### 1. Custom Section Dividers

```latex
\AtBeginSection[]{
  \begin{frame}[plain]
    \begin{tikzpicture}[remember picture, overlay]
      \fill[bg] (current page.south west) rectangle (current page.north east);
      \fill[accent!10,rounded corners=20pt] 
        ([shift={(3cm,1cm)}]current page.center) +(-4,-2) rectangle +(4,2);
      \node[text=accent,font=\Huge\bfseries] 
        at ([yshift=1.5cm]current page.center) {\insertsectionnumber};
      \node[text=text1,font=\Large\bfseries] 
        at (current page.center) {\insertsection};
    \end{tikzpicture}
  \end{frame}
}
```

### 2. UI Mockups (Instead of Screenshots)

```latex
% Example: Form with fields and labels
\begin{tikzpicture}[
  field/.style={fill=surface2,rounded corners=6pt,inner sep=6pt,text width=10cm},
  label/.style={fill=surface,rounded corners=12pt,inner sep=3pt,font=\tiny\bfseries}
]
  \fill[surface,rounded corners=10pt] (-0.5,2.8) rectangle (12,-4.5);
  % Window chrome dots
  \fill[red] (0.2,2.5) circle(3pt);
  \fill[orange] (0.7,2.5) circle(3pt);
  \fill[green] (1.2,2.5) circle(3pt);
  % Title field
  \node[field] at (0.2,1.9) {\textcolor{text3}{Titel}};
  % Label pills
  \node[label=red] at (0.5,-2.1) {\textcolor{red!70!white}{Prio::Hoch}};
  % Submit button
  \fill[accent,rounded corners=6pt] (0.2,-3.2) rectangle (3,-2.6);
  \node[text=white,font=\small\bfseries] at (1.6,-2.9) {Create Issue};
\end{tikzpicture}
```

### 3. Branch/Flow Diagrams

```latex
\begin{tikzpicture}[
  commit/.style={circle,fill=#1,inner sep=5pt,font=\tiny\bfseries,text=white},
  >=Stealth
]
  \draw[accent,line width=2pt,->] (0,0) -- (11,0);     % main line
  \node[commit=accent] (c2) at (3.5,0) {2};
  \draw[pink,line width=2pt] (3.5,0) to[out=60,in=180] (5,1.5);  % branch off
  \node[commit=pink] (f1) at (5,1.5) {3};
  \draw[green,line width=2pt,dashed] (7,1.5) to[out=-30,in=120] (9.5,0);  % merge
\end{tikzpicture}
```

### 4. Kanban Board Illustration

```latex
\begin{tikzpicture}[
  col/.style={fill=surface,rounded corners=8pt,minimum height=4.5cm,minimum width=2.8cm},
  card/.style={fill=surface2,rounded corners=6pt,inner sep=5pt,text width=2.2cm,font=\scriptsize}
]
  \node[col] (todo) at (0,0) {};
  \node[card,anchor=north west] at (0.3,-0.1) {\textcolor{text1}{Login-Seite}\\[2pt]\labtag{red}{Hoch}};
  % ... more columns and cards
\end{tikzpicture}
```

### 5. Clickable Table of Contents (hyperref)

```latex
\node[circle,fill=accent,text=white,inner sep=4pt] at (0,0) {1};
\node[anchor=west] at (0.8,0) {\hyperlink{sec:issues}{Issues}};
% Target:
\section{Issues}
\label{sec:issues}  % \hypertarget{sec:issues}{} works too
```

### 6. Do/Don't Comparison

```latex
\begin{columns}[T]
\begin{column}{0.48\textwidth}
\begin{alertblock}{\faTimes~Don't}
  \begin{itemize} \item Bad practice \end{itemize}
\end{alertblock}
\end{column}
\begin{column}{0.48\textwidth}
\begin{exampleblock}{\faCheck~Do}
  \begin{itemize} \item Good practice \end{itemize}
\end{exampleblock}
\end{column}
\end{columns}
```

## Compilation

Always run **twice** for correct hyperlinks and TOC:

```bash
pdflatex -interaction=nonstopmode file.tex
pdflatex -interaction=nonstopmode file.tex
```

## Pitfalls

- **fontawesome5 missing**: `sudo apt-get install -y texlive-fonts-extra` — takes ~2 min
- **German umlauts**: Use `\"A`, `\"O`, `\"U`, `\"a`, `\"o`, `\"u`, `\ss` for ß in TikZ nodes. UTF-8 works in frame text but NOT reliably inside TikZ nodes with some engines.
- **Beamer + remember picture overlay**: Needs TWO compilation passes for correct positioning
- **Color names in TikZ style params**: Can't use custom colors directly as `fill=accent` in style definitions — use `fill=#1` with color passed as param
- **text width + font size**: TikZ nodes need `text width` for wrapping. Without it, long text overflows
- **No `\bottomrule` in Beamer**: Tables in Beamer frames should use simpler formatting — `\bottomrule` from booktabs can cause issues in some Beamer themes

## Cheatsheet: What to Illustrate Without Screenshots

| UI Element | TikZ Approach |
|------------|---------------|
| Form/Input fields | `rounded corners=6pt` rectangles with placeholder text |
| Label pills/tags | `rounded corners=12pt` small rectangles with colored fills |
| Dropdown menus | Rectangle + triangle character `$\triangledown$` |
| Buttons | Filled rounded rectangles with white text |
| Progress bars | `\fill[accent] (0,0) rectangle (5,0.3);` |
| Modals/Dialogs | Large rounded rectangle over `remember picture, overlay` background |
| Kanban columns | Vertical rounded rectangles with smaller card rectangles inside |
| Timeline/Milestones | Horizontal line + circle nodes with labels |
| Burndown charts | Axes + `\draw` line plots with circle dots at data points |
| Flow arrows | `arrows.meta` library, `dashed` for optional flows |