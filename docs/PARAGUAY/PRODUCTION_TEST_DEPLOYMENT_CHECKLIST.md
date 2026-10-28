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
- [x] Configure final cashier, fiscal operator, administrator and KDS roles.
      Revalidated on 2026-10-28: the primary administrator retains Settings,
      POS Manager, KDS Manager and Paraguay Fiscal Operator; the functional
      administrator retains Access Rights, POS Manager and KDS Manager without
      technical Settings or fiscal-submission authority.

## Application deployment

- [x] Deploy the tagged Odoo 17 baseline. AWS STAGING was fast-forwarded to
      published commit `3ed1714` on 2026-10-28; operational configuration and
      secrets remain intentionally untracked.
- [x] Install/upgrade `kds_module`, `einvoice_module`, `einvoice_py` and
      `einvoice_py_pos` only as required by the selected product package.
- [x] Configure company, taxes, POS, payment mappings, establishment and point
      of issue.
- [x] Configure Amazon SES and verify KuDE/XML delivery. The active STAGING
      server uses the us-east-1 SES SMTP endpoint with STARTTLS; authoritative
      PDF/XML MIME integrity and delivery were already validated by the V1
      acceptance evidence and were not resent during the 2026-10-28 audit.

## SIFEN TEST safety gate

- [x] Confirm every Paraguay adapter is `TEST`.
- [x] Confirm only TEST endpoints, timbrado and CSC are configured.
- [x] Confirm production activation guard rejects incomplete or mixed settings.
- [x] Display the TEST/no-fiscal-validity status clearly to operators.
- [x] Keep automatic retry disabled unless explicitly approved and monitored.
      The fiscal POS has automatic submission disabled and the 2026-10-28
      audit found zero queued or pending fiscal documents.

## Operational acceptance

- [x] Validate no-FE, innominado FE and identified-RUC FE checkout paths.
      Current STAGING evidence preserves ordinary paid no-FE orders and POS
      innominado order `POS Fiscal SIFEN STAGING/0001`; its fiscal document `2`
      is accepted in TEST with authority code `0260` and protocol `50282539`.
      Identified-RUC FE remains covered by the accepted B2B evidence recorded
      in the homologation matrix and by the unchanged complete AWS acceptance
      suite; no duplicate fiscal POST was made for this final audit.
- [x] Validate local-first RUC lookup and TEST authority fallback.
- [x] Validate cash, card, transfer/QR and mixed payments.
- [x] Validate acceptance, rejection, ambiguity and restart idempotency.
- [x] Validate authoritative KuDE/XML download and email delivery.
- [x] Validate KDS order, quantity change, cancellation and status transitions.
- [x] Confirm logs and support diagnostics without exposing fiscal data.
      PostgreSQL, Odoo and the ePOS simulator use bounded Docker logs. After
      the fiscal module upgrade and restart on 2026-10-28, registry loading and
      authenticated route redirection were healthy and the post-restart log
      contained no ERROR, CRITICAL or traceback entry. AWS disk alerting stays
      separately pending because custom metrics may add cost.

## Final STAGING V1 acceptance — 2026-10-28

- Database: `restaurant_staging`.
- Installed versions: `einvoice_module` 17.0.1.0.0, `einvoice_py`
  17.0.1.0.3, `einvoice_py_pos` 17.0.1.5.0 and `kds_module` 17.0.1.1.4.
- The schema was upgraded only for the three fiscal modules after a verified
  PostgreSQL-plus-filestore backup. Odoo registry and HTTP login returned
  healthy after restart.
- Adapter `Paraguay SIFEN TEST` is active in `test`, with
  `production_enabled=False` and external-secret credentials. The certificate
  and password references were present and readable without exposing values.
- Durable fiscal state at audit time: one accepted TEST document, zero queued,
  zero pending and zero failed-final documents. The audit itself made zero
  SIFEN requests.
- GitHub, the local checkout and AWS STAGING all resolve the deployed baseline
  to commit `3ed171476f85fea2b9eb4a84ae0aedbfe47f06f5`; only environment-specific
  configuration and secret directories remain untracked on STAGING.

## Pilot and later production switch

- [ ] Complete a supported TEST pilot with one or two low-volume businesses.
- [ ] Complete the DNIT-confirmed homologation scope.
- [ ] Obtain explicit DNIT production habilitation.
- [ ] Perform a separately reviewed and authorized switch to SIFEN PRODUCTION.
