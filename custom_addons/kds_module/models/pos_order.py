import hashlib
import json
import logging

from odoo import api, models


_logger = logging.getLogger(__name__)


class PosOrder(models.Model):
    _inherit = "pos.order"

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
            )
