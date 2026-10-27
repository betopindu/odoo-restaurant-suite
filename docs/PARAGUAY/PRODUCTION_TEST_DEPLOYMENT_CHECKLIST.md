# Commercial V1 deployment checklist — SIFEN TEST

This checklist tracks deployment of Commercial V1 on operational
infrastructure while Paraguay fiscal traffic remains strictly in SIFEN TEST.
It is not evidence of DNIT production habilitation.

## Baseline

- [x] Commercial V1 implementation and clean local acceptance completed.
- [x] AWS STAGING acceptance completed.
- [x] Pre-habilitation TEST-only deployment decision documented.
- [x] Decision documentation published at commit `0262379`.
- [x] Create and publish the immutable deployment baseline tag
      `commercial-v1-sifen-test`.

## Infrastructure and persistence

- [ ] Create or designate the operational AWS environment separately from STAGING.
      Read-only audit on 2026-10-27 found only `odoo-staging`
      (`i-016056d5e7c5fdcca`, `t3.micro`, `us-east-1c`); no separate operational
      instance currently exists.
- [ ] Configure persistent PostgreSQL and Odoo filestore storage.
- [ ] Configure backups and complete one verified restoration.
- [ ] Confirm capacity, disk monitoring and restart policy.

## Security and access

- [ ] Install trusted HTTPS and a stable public hostname.
- [ ] Publish Odoo only through the HTTPS reverse proxy.
- [ ] Restrict SSH and remove public direct access to Odoo port 8069.
- [ ] Store certificate, password, CSC and SMTP credentials in managed secrets.
- [ ] Configure final cashier, fiscal operator, administrator and KDS roles.

## Application deployment

- [ ] Deploy the tagged Odoo 17 baseline.
- [ ] Install/upgrade `kds_module`, `einvoice_module`, `einvoice_py` and
      `einvoice_py_pos` only as required by the selected product package.
- [ ] Configure company, taxes, POS, payment mappings, establishment and point
      of issue.
- [ ] Configure Amazon SES and verify KuDE/XML delivery.

## SIFEN TEST safety gate

- [ ] Confirm every Paraguay adapter is `TEST`.
- [ ] Confirm only TEST endpoints, timbrado and CSC are configured.
- [ ] Confirm production activation guard rejects incomplete or mixed settings.
- [ ] Display the TEST/no-fiscal-validity status clearly to operators.
- [ ] Keep automatic retry disabled unless explicitly approved and monitored.

## Operational acceptance

- [ ] Validate no-FE, innominado FE and identified-RUC FE checkout paths.
- [ ] Validate local-first RUC lookup and TEST authority fallback.
- [ ] Validate cash, card, transfer/QR and mixed payments.
- [ ] Validate acceptance, rejection, ambiguity and restart idempotency.
- [ ] Validate authoritative KuDE/XML download and email delivery.
- [ ] Validate KDS order, quantity change, cancellation and status transitions.
- [ ] Confirm logs, alerts and support procedure without exposing fiscal data.

## Pilot and later production switch

- [ ] Complete a supported TEST pilot with one or two low-volume businesses.
- [ ] Complete the DNIT-confirmed homologation scope.
- [ ] Obtain explicit DNIT production habilitation.
- [ ] Perform a separately reviewed and authorized switch to SIFEN PRODUCTION.
