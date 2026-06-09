# Diagrams Hub

[Documentation Home](../README.md) -> [Documentation Index](../index.md) -> Diagrams

This page is the visual navigation hub for the e-Invoice Platform.

## Architecture Diagram

**Purpose:** Show the high-level platform flow.

**Short description:** The architecture diagram shows how the Fiscal API creates fiscal documents, how the orchestrator delegates to country adapters, and where payload, schema-oriented unsigned XML, future signature, and future tax authority integration fit.

**Diagram:** [architecture.mmd](architecture.mmd)

**Related documentation:**

* [Architecture](../ARCHITECTURE.md)
* [ADR-001 Country Addons](../ADR/ADR-001-country-addons.md)
* [ADR-006 API Processing Modes](../ADR/ADR-006-api-processing-modes.md)

## Workflow Diagram

**Purpose:** Provide a simple workflow overview.

**Short description:** The workflow diagram gives a compact view of the main fiscal document outcomes from queued processing.

**Diagram:** [workflow.mmd](workflow.mmd)

**Related documentation:**

* [Architecture](../ARCHITECTURE.md)
* [ADR-005 Fiscal Lock Policies](../ADR/ADR-005-fiscal-lock-policies.md)

## Fiscal State Machine

**Purpose:** Document the full fiscal state model.

**Short description:** The fiscal state machine includes draft, ready, queued, submitted, accepted, rejected, failed retryable, failed final, manual review, validation error, and cancelled transitions.

**Diagram:** [fiscal-state-machine.mmd](fiscal-state-machine.mmd)

**Related documentation:**

* [Architecture](../ARCHITECTURE.md)
* [Roadmap](../ROADMAP.md)
* [ADR-005 Fiscal Lock Policies](../ADR/ADR-005-fiscal-lock-policies.md)

## Paraguay Processing Flow

**Purpose:** Show the implemented Paraguay-specific processing order.

**Short description:** The Paraguay processing diagram shows how a fiscal document uses issuer, establishment, point of issue, sequence, CDC, payload JSON, and schema-oriented unsigned XML before the current fake adapter outcome.

**Diagram:** [paraguay-processing.mmd](paraguay-processing.mmd)

**Related documentation:**

* [Paraguay Documentation](../PARAGUAY/README.md)
* [ADR-008 Paraguay Numbering Before CDC](../ADR/ADR-008-paraguay-numbering-before-cdc.md)
* [ADR-009 CSC Only For QR](../ADR/ADR-009-csc-only-for-qr.md)

## Related Documents

* [Documentation Home](../README.md)
* [Documentation Index](../index.md)
* [Architecture](../ARCHITECTURE.md)
* [Paraguay Documentation](../PARAGUAY/README.md)

## Next Recommended Reading

* [Architecture](../ARCHITECTURE.md)
* [Paraguay Documentation](../PARAGUAY/README.md)
