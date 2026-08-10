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
[x] Stage 8.20 Concrete PKCS#12 Material Provider
[x] Stage 8.21 Qualified Certificate Installation Validation
[x] Stage 8.22 Live TEST mTLS Preflight
[x] Stage 8.24A SIFEN Consulta DE and ambiguous submission reconciliation
[x] Production-safe Consulta DE observability and state reconciliation
[x] Paraguay v150 receiver-event flows (offline implementation)
[ ] Live TEST validation of receiver events
[x] Paraguay SIFEN cancellation and number inutilization flows
[x] Stage 8.25 SIFEN TEST homologation profile and readiness status
[x] Stage 8.26 SIFEN XMLDSig signing engine
[x] Stage 8.27 SIFEN QR payload and gCamFuFD builder
[x] Stage 8.28 Final rDE assembly and XSD validation
[x] Stage 8.29 SIFEN SOAP envelope builder
[x] Stage 8.29A Audit SOAP envelope against official SIFEN contract
[x] Stage 8.30 SIFEN TEST SOAP client
[x] Stage 8.31 Parse and classify SIFEN siRecepDE responses
[x] Stage 8.32 End-to-end SIFEN TEST submission
[x] Stage 8.33 Homologation readiness audit
[x] Documentation closeout for TEST-ready baseline at `cd07a73`
[x] First controlled synchronous SIFEN TEST DE accepted (`0260`)
[x] B2B TEST pipeline prepared and structurally validated with current official receiver evidence
[x] Homologation-driven timezone, artifact-versioning, VAT, catalog, and CSC corrections
[x] Official February 2026 TEST scope and repository capability matrix
[x] Paraguay fiscal data enrichment
[x] Paraguay Stage 5 stabilization and administrative UX cleanup
[x] Initial ADR documentation
[x] Deterministic, payload-first Paraguay invoice KuDE/PDF generation and artifact versioning
[x] Safe SIFEN authority-incident observability and guarded manual retry
[x] Secure recipient delivery of current accepted Paraguay rDE and KuDE artifacts
[x] Non-authoritative, ephemeral Paraguay KuDE Preview separated from delivery

## Current Baseline

The repository has completed its first accepted live TEST submission. SIFEN
accepted document 16106 through transmission 17896 with code `0260`
(`Autorización del DE satisfactoria`). This validates the complete synchronous
path for that invoice profile: qualified credential resolution, XMLDSig, QR,
official XSD validation, SOAP 1.2, mTLS, response parsing, and persistence.

The result does not certify every SIFEN document type or business scenario and
does not authorize production operation.

## Current Validation Status

After accepted-document delivery validation, the full `einvoice_py` suite
reports **548 counted tests across 484 test methods**. Automated coverage is
network-free.
It proves local v150 XML construction, XMLDSig, QR, final XSD validation, SOAP
1.2 wrapping, mocked mTLS transport, response classification, readiness, and
end-to-end composition. Live acceptance is recorded separately above and is
limited to the exercised invoice profile.

## Next

[x] Resolve the B2B TEST receiver-data gate using a DNIT-published electronic taxpayer
[x] Prepare and validate a fresh two-item B2B FE offline (document `17894`)
[ ] Submit the fresh B2B FE once under separate controlled authorization
[ ] Execute it live only under separate authorization
[ ] Complete the authority-defined TEST homologation case matrix
[ ] Apply further interoperability corrections only when supported by authority evidence
[ ] Stage 8.24B durable pre-POST persistence, explicitly postponed until homologation evidence justifies it
[ ] Production connection preflight
[ ] Paraguay adapter integration
[ ] Retry cron activation after operational approval
[ ] Operational monitoring and alerting
[ ] Production go-live
[ ] Operational KuDE delivery to receivers
[ ] KuDE profiles for additional SIFEN DTE types

## Future

[ ] SIFEN error normalization
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
