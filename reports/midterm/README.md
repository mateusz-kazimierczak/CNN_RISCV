# Midterm report

The [midterm presentation](https://docs.google.com/presentation/d/1C1yH6lDG07P288sPAHhANP2DuaQ6jViiKXMT8TjxvKU/edit?usp=sharing)
is available to anyone with the link as a viewer (Drive permissions checked
2026-10-27). It is maintained separately; no slide edits are needed for the repo.
The root [midterm index](../../README.md#midterm-submission) links the source,
experiments, measurements, verification and reproduction instructions.

`main.tex` is the report entry point. It is a self-contained, two-column article
with explicit placeholders; no results have been copied into the scaffold.
No course-specific LaTeX template was supplied, so the layout uses the standard
`article` class and can be adapted when formatting requirements are available.

## Edit and preview

Open `main.tex` in the Codex LaTeX editor for the source and live PDF preview.
Keep the report text and bibliography in this file so the editor can compile it
without additional project files. The `figures/` directory is reserved for future
assets; external figures may require the local build below.

For a local build with an existing TeX installation and `latexmk`, run from this
directory:

```sh
latexmk -pdf -interaction=nonstopmode -halt-on-error -outdir=build main.tex
```

The output is `build/main.pdf`. Remove generated files with:

```sh
latexmk -C -outdir=build main.tex
```

## Drafting outline and evidence

Use the [unified evidence package](../../results/submission/README.md) and
[hardware-era report](../../docs/hardware-optimization-report.md) for current
submission labels (A0 = LiteRT, B1.1 = custom compiler, final B1 = B1.7),
internal substages, D1 attribution and accepted cycle data.
The historical folder names `X1` and `X2` refer to initial ISA substages; the
main presentation uses their final tuned configurations.

- Introduction: project motivation, scope, and demonstrated contributions.
- Workload and setup: `../../models/README.md`, `../../tflm/README.md`, and
  `../../docs/compiler.md`.
- Baseline analysis: `../../docs/profiling.md`,
  `../../docs/compiler-profiling.md`, and `../../results/profiling/B0/`.
- Software optimizations: `../../docs/B1-software-report.md`.
- ISA design: `../../docs/xqmac8.md`, `../../docs/xrequant.md`, and
  `../../docs/xrequant-optimization.md`. Select later extensions explicitly.
- Verification and evaluation: the corresponding raw artifacts in
  `../../results/profiling/`, with commands and measurement boundaries recorded.
- Remaining work: assess current hardware and synthesis status before drafting.

The midterm emphasis comes from `../../instructions.md`: ISA and Spike with
custom instructions. Keep ISA-level evidence distinct from hardware performance
claims. The assignment's 6–8 page guidance is for the final report; this scaffold
does not assume a midterm page limit.

Replace every `\todo{...}`, fill or remove the result table, and add citations
before submission. Add plots and diagrams to `figures/` as needed.
