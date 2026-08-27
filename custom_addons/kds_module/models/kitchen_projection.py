import hashlib
import json
import logging

from psycopg2.errors import SerializationFailure

from odoo import api, fields, models
from odoo.tools import float_compare, float_is_zero


_logger = logging.getLogger(__name__)


class KitchenOrderProjection(models.Model):
    _name = "kitchen.order.projection"
    _description = "Auditable POS to KDS Projection"
    _order = "id desc"

    pos_order_id = fields.Many2one("pos.order", required=True, ondelete="cascade", index=True)
    pos_config_id = fields.Many2one(related="pos_order_id.config_id", store=True, index=True)
    company_id = fields.Many2one(related="pos_order_id.company_id", store=True, index=True)
    source_hash = fields.Char(required=True, index=True, readonly=True)
    source_snapshot_json = fields.Text(required=True, readonly=True)
    state = fields.Selection(
        [("processing", "Processing"), ("complete", "Complete"), ("failed", "Failed")],
        required=True,
        default="processing",
        index=True,
    )
    attempt_count = fields.Integer(default=1, required=True, readonly=True)
    last_error_category = fields.Char(readonly=True)
    completed_at = fields.Datetime(readonly=True)

    _sql_constraints = [
        (
            "pos_order_source_hash_unique",
            "unique(pos_order_id, source_hash)",
            "This POS source state already has a KDS projection.",
        ),
    ]

    @api.model
    def _canonical_snapshot(self, raw_snapshot):
        if isinstance(raw_snapshot, str):
            snapshot = json.loads(raw_snapshot or "{}")
        else:
            snapshot = raw_snapshot
        if not isinstance(snapshot, dict):
            raise ValueError("KDS source snapshot must be a JSON object")
        serialized = json.dumps(snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return snapshot, serialized, hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    @api.model
    def project_pos_order(self, pos_order, expected_source_hash=None):
        pos_order = pos_order.sudo().exists()
        if not pos_order:
            return self.browse()

        self.env.cr.execute("SELECT id FROM pos_order WHERE id = %s FOR UPDATE", [pos_order.id])
        pos_order.invalidate_recordset(["last_order_preparation_change"])
        snapshot, serialized, source_hash = self._canonical_snapshot(
            pos_order.last_order_preparation_change or "{}"
        )
        if expected_source_hash and source_hash != expected_source_hash:
            raise ValueError("Persisted POS preparation state changed before KDS projection")
        if not snapshot:
            return self.browse()

        projection = self.sudo().search([
            ("pos_order_id", "=", pos_order.id),
            ("source_hash", "=", source_hash),
        ], limit=1)
        if projection.state == "complete":
            return projection
        if not projection:
            now = fields.Datetime.now()
            try:
                with self.env.cr.savepoint():
                    self.env.cr.execute(
                        """
                INSERT INTO kitchen_order_projection
                    (pos_order_id, pos_config_id, company_id, source_hash,
                     source_snapshot_json, state, attempt_count,
                     create_uid, create_date, write_uid, write_date)
                VALUES (%s, %s, %s, %s, %s, 'processing', 1, %s, %s, %s, %s)
                ON CONFLICT (pos_order_id, source_hash) DO NOTHING
                RETURNING id
                        """,
                        [
                            pos_order.id,
                            pos_order.config_id.id,
                            pos_order.company_id.id,
                            source_hash,
                            serialized,
                            self.env.uid,
                            now,
                            self.env.uid,
                            now,
                        ],
                    )
                    inserted = self.env.cr.fetchone()
            except SerializationFailure:
                # A concurrent transaction committed this exact projection.
                # The savepoint keeps the POS transaction usable.
                return self.browse()
            # Under Odoo's REPEATABLE READ isolation a concurrent winner is not
            # visible in this transaction's snapshot. ON CONFLICT still waits
            # for it and makes this invocation a safe no-op.
            if not inserted:
                return self.browse()
            projection = self.sudo().browse(inserted[0])
        elif projection.state == "failed":
            projection.write({
                "state": "processing",
                "attempt_count": projection.attempt_count + 1,
                "last_error_category": False,
            })

        try:
            with self.env.cr.savepoint():
                self._apply_snapshot(pos_order, snapshot)
        except Exception as exc:
            projection.write({
                "state": "failed",
                "last_error_category": type(exc).__name__,
            })
            _logger.exception(
                "KDS projection failed for POS order %s (source %s); partial KDS writes rolled back.",
                pos_order.id,
                source_hash[:12],
            )
            return projection

        projection.write({
            "state": "complete",
            "completed_at": fields.Datetime.now(),
            "last_error_category": False,
        })
        return projection

    def action_recover(self):
        for projection in self.sudo():
            if projection.state != "failed":
                continue
            _snapshot, _serialized, current_hash = self._canonical_snapshot(
                projection.pos_order_id.last_order_preparation_change or "{}"
            )
            if current_hash != projection.source_hash:
                raise ValueError("POS source state changed; failed KDS projection cannot be recovered")
            self.project_pos_order(projection.pos_order_id, expected_source_hash=projection.source_hash)
        return True

    @api.model
    def _stable_line_key(self, pos_order, source_key, values):
        identity = values.get("line_uuid") or source_key
        if not identity:
            raise ValueError("KDS preparation line has no stable POS identity")
        return f"{pos_order.id}|{identity}"

    @api.model
    def _apply_snapshot(self, pos_order, snapshot):
        order_model = self.env["kitchen.order"].sudo()
        line_model = self.env["kitchen.order.line"].sudo()
        product_model = self.env["product.product"].sudo()
        config = pos_order.config_id
        table_name = pos_order.table_id.name if pos_order.table_id else "Sin mesa"
        lines_by_key = {}

        for source_key, values in snapshot.items():
            if not isinstance(values, dict):
                continue
            product = product_model.browse(values.get("product_id")).exists() if values.get("product_id") else False
            rounding = product.uom_id.rounding if product and product.uom_id else 0.01
            key = self._stable_line_key(pos_order, source_key, values)
            entry = lines_by_key.setdefault(key, {
                "product": product,
                "product_name": values.get("name") or (product.display_name if product else "Producto"),
                "qty": 0.0,
                "note": values.get("note") or "",
                "rounding": rounding,
            })
            entry["qty"] += values.get("quantity", 0.0) or 0.0

        prior = line_model.search([
            ("order_id.pos_order_id", "=", pos_order.id),
            ("pos_line_key", "!=", False),
        ])
        for key in set(prior.mapped("pos_line_key")):
            lines_by_key.setdefault(key, {
                "product": False, "product_name": "", "qty": 0.0, "note": "", "rounding": 0.01,
            })

        deltas = []
        cancellations = []
        for key, values in lines_by_key.items():
            prior_lines = prior.filtered(lambda line, k=key: line.pos_line_key == k)
            sent = sum(prior_lines.filtered(lambda line: not line.is_cancellation).mapped("qty"))
            sent -= sum(prior_lines.filtered("is_cancellation").mapped("qty"))
            delta = values["qty"] - sent
            rounding = values["rounding"]
            if float_is_zero(delta, precision_rounding=rounding):
                continue
            if float_compare(delta, 0.0, precision_rounding=rounding) > 0:
                deltas.append((key, values, delta))
                continue
            remaining = abs(delta)
            originals = prior_lines.filtered(lambda line: not line.is_cancellation and line.qty > 0).sorted(
                key=lambda line: (line.created_at, line.id), reverse=True
            )
            for original in originals:
                cancelled = sum(line_model.search([
                    ("original_line_id", "=", original.id),
                    ("is_cancellation", "=", True),
                ]).mapped("qty"))
                available = original.qty - cancelled
                if float_compare(available, 0.0, precision_rounding=rounding) <= 0:
                    continue
                qty = min(remaining, available)
                cancellations.append((key, values, qty, original))
                remaining -= qty
                if float_is_zero(remaining, precision_rounding=rounding):
                    break

        now = fields.Datetime.now()
        if deltas:
            kitchen_order = order_model.create({
                "pos_order_id": pos_order.id,
                "pos_config_id": config.id,
                "pos_reference": pos_order.pos_reference,
                "table": table_name,
                "created_at": now,
                "last_activity_at": now,
            })
            for key, values, qty in deltas:
                line_model.create({
                    "order_id": kitchen_order.id,
                    "product_id": values["product"].id if values["product"] else False,
                    "product_name": values["product_name"],
                    "qty": qty,
                    "note": values["note"],
                    "pos_line_key": key,
                    "pos_cumulative_qty": values["qty"],
                    "state": "new",
                    "created_at": now,
                })
        if cancellations:
            reference = cancellations[0][3].order_id
            change_order = order_model.create({
                "event_type": "change",
                "change_reference_order_id": reference.id,
                "pos_order_id": pos_order.id,
                "pos_config_id": config.id,
                "pos_reference": pos_order.pos_reference,
                "table": table_name,
                "created_at": now,
                "last_activity_at": now,
            })
            for key, values, qty, original in cancellations:
                line_model.create({
                    "order_id": change_order.id,
                    "product_id": original.product_id.id,
                    "product_name": original.product_name,
                    "qty": qty,
                    "note": original.note,
                    "pos_line_key": key,
                    "pos_cumulative_qty": values["qty"],
                    "is_cancellation": True,
                    "original_line_id": original.id,
                    "state": "new",
                    "created_at": now,
                })
