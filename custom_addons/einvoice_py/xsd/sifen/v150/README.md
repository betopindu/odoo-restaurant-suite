# SIFEN v150 XSD Assets

These schemas are pinned local copies of the official SIFEN v150 files
published by e-Kuatia.

Official source:

```text
https://ekuatia.set.gov.py/sifen/xsd/
```

The files under `schemas/` are preserved byte-for-byte. In particular, their
original absolute `schemaLocation` values have not been rewritten. Local
schema compilation maps the exact official URLs recorded in `manifest.json`
to the corresponding local files and does not perform runtime downloads.

`siRecepDE_v150.xsd` is the root schema. Its dependency tree is:

```text
siRecepDE_v150.xsd
└── DE_v150.xsd
    ├── xmldsig-core-schema.xsd
    ├── Paises_v100.xsd
    ├── Departamentos_v141.xsd
    ├── Monedas_v150.xsd
    ├── Unidades_Medida_v141.xsd
    └── DE_Types_v150.xsd
```

The manifest records source URLs, SHA-256 checksums, roles, dependencies, and
the no-runtime-download policy.

Full official validation of generated SIFEN XML remains a later stage. It
requires the signing and QR fields that are intentionally absent from the
current unsigned XML draft:

* `dFecFirma`
* `ds:Signature`
* `gCamFuFD/dCarQR`

## Provenance And Licensing

The seven SIFEN-owned schemas do not contain an explicit redistribution
license. They are publicly served from the official e-Kuatia endpoint and are
vendored here for deterministic validation and auditability.

`xmldsig-core-schema.xsd` contains its original W3C copyright and W3C Software
License notice. No schema file has been modified.
