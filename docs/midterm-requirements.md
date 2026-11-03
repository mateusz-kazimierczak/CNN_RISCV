# Midterm evaluation requirements

The midterm evaluates the bare-metal workload and custom instructions in Spike.
The required submission contains:

1. Source code in C/C++ for the bare-metal workload.
2. A quantized model or model-conversion scripts in Python.
3. Spike/custom-ISA implementation source code.
4. Short verification tests for the added instructions.
5. Reproducible benchmark scripts for full-workload evaluation.
6. A slides presentation lasting 5–6 minutes.
7. A GitHub README explaining how to run the tests and scripts and stating
   expected performance measurements, such as retired instruction counts.

PPA evaluation is excluded from this milestone: the midterm evaluates the ISA
rather than its implementation on CV-Wally.

The [evaluation guide](midterm-submission.md) maps these items to the project
artifacts and reproduction commands. The [term-project assignment](../instructions.md)
and [runtime clarifications](../clarifications.md) provide the broader project
context and final-stage requirements.
