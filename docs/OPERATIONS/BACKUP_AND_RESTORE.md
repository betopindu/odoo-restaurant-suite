# Odoo database and filestore backup

An Odoo recovery point is complete only when PostgreSQL and the matching
filestore are preserved together. Docker named volumes protect against
container recreation, but not against loss or corruption of the EC2/EBS host.

## Create a consistent bundle

Run from the deployed repository directory. The command stops only Odoo for
the duration of the snapshot, keeps PostgreSQL running for `pg_dump`, captures
the matching filestore, validates both archives, records safe metadata and
restarts Odoo through an exit trap.

```bash
DB_NAME=restaurant_staging \
COMPOSE_FILE_PATH=docker-compose.staging.yml \
BACKUP_ROOT=/opt/odoo/backups \
scripts/backup_odoo_bundle.sh
```

The resulting directory contains:

- `database.dump` — PostgreSQL custom-format dump;
- `filestore.tar.gz` — the matching Odoo filestore directory;
- `manifest.txt` — database, timestamp, source revision and service names;
- `SHA256SUMS` — integrity hashes.

No `.env`, certificate, private key, CSC or password is copied into the
bundle. The fiscal and customer data inside the database and filestore remain
sensitive. Files are created with owner-only permissions.

## Verify before transfer

```bash
scripts/verify_odoo_bundle.sh /opt/odoo/backups/BUNDLE_DIRECTORY
```

Copy the complete directory over an encrypted channel to storage outside the
EC2 instance, verify the hashes again at the destination, and retain it only on
encrypted, access-controlled storage. A backup left solely on the same EC2 is
not a disaster-recovery copy.

## Restoration test boundary

A restoration test must use an isolated database name and isolated filestore;
it must never overwrite `restaurant_staging`. Restore the PostgreSQL custom
dump with `pg_restore`, extract the filestore under the exact isolated database
name, start an isolated Odoo process, and verify registry load, attachment
access and record counts. Delete the isolated restoration only after evidence
has been recorded.

The first AWS restoration exercise remains pending until a current bundle has
been copied outside EC2.

