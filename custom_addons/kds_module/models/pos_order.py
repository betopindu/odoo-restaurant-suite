import hashlib
import json
import logging

from odoo import api, fields, models
from odoo.exceptions import ValidationError


_logger = logging.getLogger(__name__)


class PosOrder(models.Model):
    _inherit = "pos.order"

    kds_preparation_revision = fields.Integer(
        copy=False,
        readonly=True,
        help="Monotonic identity of the latest native POS preparation event.",
    )

    @api.model
    def _order_fields(self, ui_order):
        values = super()._order_fields(ui_order)
        if "kds_preparation_revision" in ui_order:
            values["kds_preparation_revision"] = self._kds_ui_revision(ui_order)
        return values

    @api.model
    def _process_order(self, order, draft, existing_order):
        data = order.get("data", {})
        if existing_order and "kds_preparation_revision" in data:
            incoming_revision = self._kds_ui_revision(data)
            current_revision = existing_order.kds_preparation_revision or 0
            if incoming_revision < current_revision:
                raise ValidationError("POS preparation revision cannot move backwards.")
            if incoming_revision == current_revision and incoming_revision:
                _snapshot, incoming_serialized = self._kds_canonical_snapshot(
                    data.get("last_order_preparation_change")
                )
                _snapshot, current_serialized = self._kds_canonical_snapshot(
                    existing_order.last_order_preparation_change
                )
                if incoming_serialized != current_serialized:
                    raise ValidationError(
                        "A POS preparation revision cannot contain different snapshots."
                    )
        return super()._process_order(order, draft, existing_order)

    @api.model
    def _export_for_ui(self, order):
        values = super()._export_for_ui(order)
        values["kds_preparation_revision"] = order.kds_preparation_revision or 0
        return values

    @api.model
    def _kds_ui_revision(self, data):
        try:
            revision = int(data.get("kds_preparation_revision") or 0)
        except (TypeError, ValueError):
            raise ValidationError("POS preparation revision must be an integer.") from None
        if revision < 0:
            raise ValidationError("POS preparation revision cannot be negative.")
        return revision

    @api.model
    def _kds_canonical_snapshot(self, raw_snapshot):
        try:
            snapshot = json.loads(raw_snapshot or "{}") if isinstance(raw_snapshot, str) else raw_snapshot
        except (TypeError, ValueError):
            raise ValidationError("POS preparation snapshot must be valid JSON.") from None
        if not isinstance(snapshot, dict):
            raise ValidationError("POS preparation snapshot must be an object.")
        return snapshot, json.dumps(
            snapshot,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )

    @api.model
    def create_from_ui(self, orders, draft=False):
        result = super().create_from_ui(orders, draft=draft)
        try:
            with self.env.cr.savepoint():
                self._sync_kds_from_ui_result(orders, result)
        except Exception:
            _logger.exception(
                "KDS synchronization failed after POS order creation; preserving POS create_from_ui result."
            )
        return result

    def _sync_kds_from_ui_result(self, orders, result):
        result_by_reference = {
            item.get("pos_reference"): item.get("id")
            for item in result
            if item.get("pos_reference") and item.get("id")
        }
        for ui_order in orders:
            data = ui_order.get("data", {})
            order_id = result_by_reference.get(data.get("name"))
            pos_order = self.browse(order_id).exists() if order_id else self.browse()
            if not pos_order:
                continue
            try:
                snapshot = json.loads(data.get("last_order_preparation_change") or "{}")
                canonical = json.dumps(snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            except (TypeError, ValueError):
                continue
            expected_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
            self.env["kitchen.order.projection"].sudo().project_pos_order(
                pos_order,
                expected_source_hash=expected_hash,
                expected_source_revision=(
                    self._kds_ui_revision(data) or None
                    if "kds_preparation_revision" in data
                    else None
                ),
            )
