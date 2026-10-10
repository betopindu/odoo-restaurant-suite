# Epson ePOS simulator (STAGING only)

This tool emulates the Epson ePOS HTTP endpoint used by Odoo 17 preparation
printers. It is a development and staging aid, not a production printing
service and not part of `kds_module`.

It accepts Odoo's rasterized ePOS request, returns the standard successful
response, stores the original request with mode `0600`, renders a PNG preview,
and exposes a token-protected review page. It retains at most 200 jobs by
default. Tokens and captured jobs are intentionally ignored by Git.

## Run

1. Copy `epos.env.example` to `epos.env` and generate a random token with
   `openssl rand -hex 24`.
2. Start the override alongside the normal stack:

   ```bash
   docker compose -f docker-compose.staging.yml \
     -f tools/epos_simulator/docker-compose.epos.yml up -d epos_simulator
   ```

3. Prefer SSH tunnels instead of a public security-group rule:

   ```bash
   ssh -N \
     -L 127.0.0.1:18069:127.0.0.1:8069 \
     -L 127.0.0.1:9000:127.0.0.1:9000 \
     ubuntu@STAGING_HOST
   ```

4. Open Odoo through `http://127.0.0.1:18069`, configure the Epson preparation
   printer as `127.0.0.1:9000`, and review jobs at
   `http://127.0.0.1:9000/review?token=TOKEN`.

Opening Odoo from its public IP while targeting a loopback printer is not
supported: modern browsers block that public-to-local-network request.

## Automated checks

Run `python3 -m unittest tools.epos_simulator.test_server`. The checks cover
protocol acceptance, PNG rendering, protected review access, invalid requests,
and retention. KDS quantity delta, cancellation, reconnect/replay, and payment
idempotency remain covered by `kds_module` tests. A final browser smoke test is
still required to prove the standard Odoo POS emits no extra ePOS request on
payment in the deployed Odoo build.

## Security and cleanup

- Do not commit `epos.env`, captured XML, metadata, or PNG files.
- Keep port 9000 closed publicly; use the SSH tunnel.
- Captures may contain order information and must be treated as staging data.
- Stop with `docker compose -f docker-compose.staging.yml -f
  tools/epos_simulator/docker-compose.epos.yml stop epos_simulator`.
- Remove captures by deleting only files under `tools/epos_simulator/data/`
  after the required evidence has been recorded.
