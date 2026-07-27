Documentation > ADR > ADR-014 Paraguay TEST Timbrado Profile

# ADR-014: Paraguay TEST Timbrado Profile

## Status

Accepted

## Date

2026-07-26

## Context

SIFEN TEST homologation uses configuration supplied for testing, while
production electronic timbrado is an authority-controlled operational process.
Documentation must not imply that the TEST convention enables production.

## Decision

For the TEST readiness profile, the timbrado number is the taxpayer RUC
without DV, the start date is the Form 364 date, and establishment and
expedition-point codes contain exactly three digits.

TEST and PRODUCTION configuration remain separate. This baseline does not
implement or claim a production electronic timbrado workflow.

## Consequences

* TEST readiness can be evaluated deterministically.
* TEST values must not be copied into production.
* Production enablement remains pending separate authority configuration.

## Alternatives Considered

* Reuse TEST timbrado configuration in production.
  * Rejected because it would misrepresent authority-issued production data.
* Leave TEST rules implicit in the runbook.
  * Rejected because readiness validation and operator configuration must agree.

## Related Documents

* [Configuration Reference](../PARAGUAY/CONFIGURATION.md)
* [Paraguay Documentation](../PARAGUAY/README.md)
* [Roadmap](../ROADMAP.md)
