# LaTeX report template

This directory contains a self-contained, two-column LaTeX drafting template in
`main.tex`. Its sections and result table contain placeholders; it is not a
completed evaluation report.

The midterm evaluation is documented in the [project README](../../README.md#midterm-submission),
[evaluation guide](../../docs/midterm-submission.md), and
[measured results](../../results/midterm/README.md). The accompanying
[presentation](https://docs.google.com/presentation/d/1C1yH6lDG07P288sPAHhANP2DuaQ6jViiKXMT8TjxvKU/edit?usp=sharing)
is maintained in Google Slides.

## Source layout

`main.tex` uses the standard `article` class, with its text and bibliography in
one file. `figures/` is reserved for report assets. The template does not include
a course-specific style or a compiled report.

## Compile the template

With an installed TeX distribution and `latexmk`, run from this directory:

```sh
latexmk -pdf -interaction=nonstopmode -halt-on-error -outdir=build main.tex
```

The output is `build/main.pdf`. The Codex LaTeX editor can also open `main.tex`
with a live PDF preview. Generated TeX files can be removed with:

```sh
latexmk -C -outdir=build main.tex
```

## Evaluation references

- [Model and quantization](../../models/README.md)
- [Baseline characterization](../../results/profiling/B0/analysis.md)
- [Cumulative software analysis](../../docs/B1-software-report.md)
- [ISA design and comparisons](../../docs/hardware-optimization-report.md)
- [Midterm ISA measurements](../../results/midterm/README.md)
- [Additional RTL measurements](../../results/profiling/hardware-progression/README.md)

The evaluation labels are A0 for LiteRT, B1.1 for the custom compiler, and B1.7
for accepted software B1. Historical implementation names remain in the evidence
paths. Instruction-count comparisons and RTL cycle measurements have separate
measurement boundaries and provenance.
