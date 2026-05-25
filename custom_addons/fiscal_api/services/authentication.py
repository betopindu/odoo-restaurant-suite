import hashlib
import hmac
import secrets

from odoo import fields


class FiscalApiAuthenticationService:
    HASH_ALGORITHM = "sha256"
    HASH_ITERATIONS = 260000
    KEY_PREFIX_LENGTH = 12

    def __init__(self, env):
        self.env = env

    def generate_raw_key(self):
        return f"fapi_{secrets.token_urlsafe(32)}"

    def key_prefix(self, raw_key):
        return raw_key[:self.KEY_PREFIX_LENGTH]

    def hash_key(self, raw_key):
        salt = secrets.token_bytes(16)
        digest = hashlib.pbkdf2_hmac(
            self.HASH_ALGORITHM,
            raw_key.encode("utf-8"),
            salt,
            self.HASH_ITERATIONS,
        )
        return (
            f"pbkdf2_{self.HASH_ALGORITHM}${self.HASH_ITERATIONS}$"
            f"{salt.hex()}${digest.hex()}"
        )

    def verify_key(self, raw_key, stored_hash):
        try:
            scheme, iterations, salt_hex, digest_hex = stored_hash.split("$", 3)
            if scheme != f"pbkdf2_{self.HASH_ALGORITHM}":
                return False
            digest = hashlib.pbkdf2_hmac(
                self.HASH_ALGORITHM,
                raw_key.encode("utf-8"),
                bytes.fromhex(salt_hex),
                int(iterations),
            )
        except (AttributeError, TypeError, ValueError):
            return False
        return hmac.compare_digest(digest.hex(), digest_hex)

    def authenticate(self, raw_key):
        if not raw_key:
            return self.env["fiscal.api.key"].browse(), "invalid"

        candidates = self.env["fiscal.api.key"].sudo().search([
            ("key_prefix", "=", self.key_prefix(raw_key)),
        ])
        now = fields.Datetime.now()
        for candidate in candidates:
            if not self.verify_key(raw_key, candidate.key_hash):
                continue
            if not candidate.active:
                return candidate, "inactive"
            if candidate.revoked_at:
                return candidate, "revoked"
            if candidate.expires_at and candidate.expires_at <= now:
                return candidate, "expired"
            return candidate, "valid"
        return self.env["fiscal.api.key"].browse(), "invalid"

    def find_key(self, raw_key):
        api_key, status = self.authenticate(raw_key)
        if status == "valid":
            return api_key
        return self.env["fiscal.api.key"].browse()
