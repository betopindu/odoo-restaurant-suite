Documentation > ADR > ADR-006 API Processing Modes

[Documentation Home](../README.md)
-> [Architecture](../ARCHITECTURE.md)
-> [ADRs](../index.md#adrs)
-> [Paraguay](../PARAGUAY/README.md)
-> [Diagrams](../diagrams/README.md)

# Title

ADR-006: API Processing Modes

## Status

Accepted

## Date

2026-06-07

## Context

The public fiscal API supports document creation by external systems. Some clients need a non-blocking API call that queues processing, while others need a short synchronous attempt that returns a final result when processing completes quickly.

The implemented API supports `async` and `sync` processing modes. The mode is resolved from the request payload first, then from the API key default, and finally defaults to `async`.

## Decision

Support both asynchronous and synchronous API processing modes.

Synchronous processing waits only briefly. If a terminal state is not reached before timeout, the API returns an asynchronous continuation response instead of treating timeout as an error.

## Consequences

* API clients can choose between immediate queueing and short synchronous processing.
* The API does not block indefinitely.
* Timeout fallback remains part of normal processing, not an error condition.
* Status polling remains necessary for documents that continue asynchronously.
* API tests must cover invalid keys, async creation, sync processing, idempotency, and tenant isolation.

## Alternatives Considered

* Async-only API.
  * Rejected because some integrations benefit from short synchronous final responses.
* Sync-only API.
  * Rejected because authority processing may take longer than an HTTP request should block.
* Long blocking sync requests.
  * Rejected because they increase operational risk and complicate client behavior.

## Related ADRs

* [ADR-004: Multi-Tenant Shared Core](ADR-004-multi-tenant-shared-core.md)
* [ADR-007: Fiscal Attachments](ADR-007-fiscal-attachments.md)

## Related Documents

* [Documentation Home](../README.md)
* [Documentation Index](../index.md)
* [Architecture](../ARCHITECTURE.md)
* [Workflow Diagram](../diagrams/workflow.mmd)

## Next Recommended Reading

* [ADR-007 Fiscal Attachments](ADR-007-fiscal-attachments.md)
* [Workflow Diagram](../diagrams/workflow.mmd)
