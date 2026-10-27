#!/usr/bin/env bash
set -euo pipefail

BUNDLE_DIR=${1:?Usage: verify_odoo_bundle.sh BUNDLE_DIR}

for file in database.dump filestore.tar.gz manifest.txt SHA256SUMS; do
    test -f "$BUNDLE_DIR/$file" || {
        echo "Missing backup component: $file" >&2
        exit 1
    }
done

if command -v sha256sum >/dev/null 2>&1; then
    (cd "$BUNDLE_DIR" && sha256sum --check SHA256SUMS)
else
    (cd "$BUNDLE_DIR" && shasum -a 256 --check SHA256SUMS)
fi

tar -tzf "$BUNDLE_DIR/filestore.tar.gz" >/dev/null
grep -q '^format=odoo-backup-bundle-v1$' "$BUNDLE_DIR/manifest.txt"
grep -q '^database=' "$BUNDLE_DIR/manifest.txt"

echo "Backup bundle integrity verified: $BUNDLE_DIR"

