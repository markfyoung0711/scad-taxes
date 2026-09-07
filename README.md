# scad-taxes

Smith County Appraisal District taxes are worth reviewing when valuations rise sharply without a clear, documented justification. This repository is intentionally conservative: it is not an accusation, but a tool for evidence-first review.

The project provides a small Python utility to compare appraisal values over time and flag increases that are large enough to warrant review when supporting documentation is missing. It is designed to support a public exposition only when the facts are provable.

## Evidence-first stance

- Review the numbers before making claims.
- Separate a valuation change from a documented, lawful basis.
- Require supporting evidence before drawing conclusions.
- Focus on provable facts rather than speculation.

## Quick start

```bash
python scad_taxes.py examples/scad_sample_records.json
```

This emits a JSON report with suspicious appraisal increases. For example, a jump above 20% without supporting evidence is flagged for further review.
