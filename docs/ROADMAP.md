# Roadmap

[Documentation Home](README.md) -> Roadmap

[Documentation Home](README.md)
-> [Architecture](ARCHITECTURE.md)
-> [Paraguay](PARAGUAY/README.md)
-> [Diagrams](diagrams/README.md)

## Completed

[x] Core workflow
[x] Fiscal events
[x] Attachments
[x] Retry processing
[x] Lock policies
[x] API
[x] API status endpoint
[x] API sync processing with timeout fallback
[x] Idempotency
[x] Tenant isolation
[x] Paraguay issuer
[x] Paraguay establishment
[x] Paraguay point of issue
[x] Paraguay timbrado
[x] Paraguay CSC
[x] Paraguay sequence
[x] Paraguay numbering
[x] Paraguay CDC
[x] Paraguay payload
[x] Paraguay unsigned XML draft builder
[x] Paraguay XML structural alignment with SIFEN-oriented namespace and groups
[x] Paraguay issuer schema-readiness configuration
[x] Paraguay receiver schema-readiness snapshot fields
[x] Paraguay payload schema-readiness extensions
[x] Paraguay XML schema-readiness emission
[x] Paraguay pre-signature XML validation harness
[x] Paraguay SIFEN XSD asset strategy documentation
[x] Paraguay local XSD validation infrastructure
[x] Paraguay local XSD validation infrastructure hardening
[x] Paraguay official SIFEN v150 XSD asset pinning
[x] Paraguay digital signature strategy ADR
[x] Paraguay xmlsec-enabled Odoo runtime
[x] Paraguay certificate inspection service
[x] Tenant-safe fiscal credential reference architecture
[x] Separate XML-signing and mutual-TLS credential role bindings
[x] Paraguay signed XML preparation with dFecFirma
[x] Paraguay XMLDSig generation service
[x] Paraguay local XMLDSig verification service
[x] Paraguay signed XML attachment persistence
[x] Paraguay end-to-end signing pipeline service
[x] Paraguay QR payload generation
[x] Paraguay full official XSD validation after signature and QR
[x] Paraguay SIFEN test submission service
[x] Paraguay SIFEN sandbox mutual-TLS transport
[x] Paraguay SIFEN sandbox mTLS connection verification
[x] Paraguay SIFEN test submission pipeline orchestration
[x] Paraguay SIFEN fiscal transmission persistence
[x] Paraguay SIFEN retry scheduling
[x] Paraguay SIFEN callable retry execution
[x] Paraguay SIFEN automatic retry runner
[x] Stage 8.9 Paraguay SIFEN credential provider
[x] Stage 8.10 Generic Paraguay SIFEN submission
[x] Stage 8.11 Paraguay SIFEN production persistence
[x] Stage 8.12 Paraguay SIFEN production retry
[x] Stage 8.13 Paraguay SIFEN production end-to-end integration test
[x] Stage 8.15 Paraguay SIFEN automatic credential resolution at persistence
[x] Stage 8.16 Paraguay SIFEN autonomous retry input reconstruction
[x] Stage 8.17 Paraguay SIFEN configuration-driven sandbox preflight
[x] Stage 8.18 Paraguay SIFEN SOAP 1.2 synchronous submission compliance
[x] Stage 8.19 Paraguay qualified certificate documentation and lifecycle ADR
[x] Paraguay fiscal data enrichment
[x] Paraguay Stage 5 stabilization and administrative UX cleanup
[x] Initial ADR documentation

## In Progress

[ ] Project documentation

## Current Validation Status

The `einvoice_py` suite currently reports 380 counted tests across 340 test methods, with production coverage for credential resolution, submission dispatch, fiscal transmission persistence, and eligible retry scheduling/execution. Stage 8.13 adds one tests-only composition scenario across those existing services. Stage 8.15 makes `PySifenTransmissionPersistenceService` resolve runtime credentials automatically when callers supply neither a runtime credential object nor legacy explicit credential arguments. Stage 8.16 lets retry execution reconstruct omitted inputs from fiscal attachments. Stage 8.17 adds `verify_document_connection()` as a configuration-driven, Paraguay TEST-only sandbox preflight that resolves endpoint, timeout, and mutual-TLS credentials from the document and delegates exclusively to the existing connection verifier. Stage 8.18 makes synchronous DE submission use SOAP 1.2 with `application/soap+xml` and the official `rEnviDe/dId/xDE/rDE` structure. The numeric, 15-digit-maximum `dId` comes from the taxpayer-controlled persistent `fiscal.adapter.config.sequence_id`. Stage fixtures configure `no_gap`, but gapless allocation is not treated as a DNIT protocol requirement. Stage 8.19 records that live SIFEN TEST acceptance requires the taxpayer's Qualified Certificate issued by a Prestador Cualificado de Servicios de Confianza (PCSC) habilitado, while the credential architecture remains provider-neutral. The coverage uses deterministic injected fixtures and makes no live SIFEN calls.

## Next

[ ] Stage 8.20 Concrete PKCS#12 Material Provider
[ ] Stage 8.21 Qualified Certificate Installation Validation
[ ] Stage 8.22 Live TEST mTLS Preflight
[ ] Stage 8.23 First Live Synchronous TEST DE
[ ] Stage 8.24 Authority-Driven Corrections, only if required by authority evidence
[ ] Real CSC validation against SIFEN behavior
[ ] Production connection preflight
[ ] Paraguay adapter integration
[ ] Retry cron activation after operational approval
[ ] Operational monitoring and alerting
[ ] Production go-live

## Future

[ ] Paraguay QR image/rendering support
[ ] SIFEN error normalization
[ ] Paraguay KuDE/PDF
[ ] Fiscal representation download security
[ ] Email delivery
[ ] WhatsApp delivery
[ ] Costa Rica addon
[ ] Argentina addon

## Related Documents

* [Documentation Home](README.md)
* [Documentation Index](index.md)
* [Architecture](ARCHITECTURE.md)
* [Paraguay Documentation](PARAGUAY/README.md)
* [ADR-001 Country Addons](ADR/ADR-001-country-addons.md)
* [Diagrams Index](diagrams/README.md)

## Next Recommended Reading

* [Paraguay Documentation](PARAGUAY/README.md)
* [Architecture](ARCHITECTURE.md)
