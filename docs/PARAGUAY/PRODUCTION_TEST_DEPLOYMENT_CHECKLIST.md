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

- [x] Retain the approved single evolving STAGING environment for the
      pre-habilitation SIFEN TEST pilot; do not create a second AWS environment
      yet. Read-only audit on 2026-10-27 confirmed `odoo-staging`
      (`i-016056d5e7c5fdcca`, `t3.micro`, `us-east-1c`).
- [x] Keep PostgreSQL and the Odoo filestore on separate persistent Docker
      named volumes so container recreation does not erase them.
- [x] Protect those volumes from EC2/EBS loss with a documented backup target
      outside the instance. Named Docker volumes alone are not a disaster
      recovery boundary.
- [x] Version a consistent PostgreSQL-plus-filestore backup and integrity
      verification procedure.
- [x] Execute the current backup, copy it outside EC2 and verify destination
      hashes.
- [x] Complete one isolated restoration test.
- [x] Confirm current capacity and restart policy. Read-only audit on 2026-10-27
      found a 20 GB root volume at 48% use (9.6 GB free), 10% inode use,
      349 MiB available RAM plus 2 GB swap, Docker enabled/active, and
      `unless-stopped` for PostgreSQL, Odoo and the staging ePOS simulator.
- [ ] Configure disk-usage monitoring and an alert threshold. The CloudWatch
      agent is not currently active; enabling custom metrics may add AWS cost.
- [x] Configure bounded Docker log rotation. PostgreSQL, Odoo and the staging
      ePOS simulator use `json-file` with `max-size=10m` and `max-file=5`;
      STAGING recreation and HTTP 200 verification completed on 2026-10-27.

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
