import json
from datetime import datetime, timedelta, timezone

from odoo import http
from odoo.http import request


class KitchenDisplay(http.Controller):

    def _get_kds_config(self):
        config = request.env["pos.config"].sudo().search([], limit=1)
        return {
            "warning": config.kds_warning_minutes or 5,
            "danger": config.kds_danger_minutes or 10,
            "refresh": config.kds_refresh_seconds or 10,
            "show_done": bool(config.kds_show_done_lane),
            "sound": bool(config.kds_enable_sound),
            "done_visible_minutes": config.kds_done_visible_minutes if config else 180,
        }

    def _priority_rank(self, order):
        rank_map = {
            "danger": 0,
            "warning": 1,
            "normal": 2,
        }
        return rank_map.get(order.age_level or "normal", 2)

    def _format_kitchen_number(self, order):
        name = order.name or ""
        sequence = name.rsplit("/", 1)[-1] if "/" in name else name
        try:
            return f"#{int(sequence)}"
        except (TypeError, ValueError):
            return name

    def _format_pos_reference(self, order):
        reference = (order.pos_reference or "").replace("Order ", "", 1)
        parts = reference.split("-")
        if len(parts) >= 2:
            return "-".join(parts[:2])
        return reference

    def _is_done_visible(self, order, done_visible_minutes):
        if order.state_summary != "done":
            return True

        if not order.last_activity_at:
            return True

        if done_visible_minutes <= 0:
            return True

        now = datetime.now(timezone.utc)
        activity_dt = order.last_activity_at
        if activity_dt.tzinfo is None:
            activity_dt = activity_dt.replace(tzinfo=timezone.utc)

        return activity_dt >= (now - timedelta(minutes=done_visible_minutes))

    def _build_display_values(self):
        orders = request.env["kitchen.order"].sudo().search([], order="created_at asc, id asc")
        kds = self._get_kds_config()

        def build_lane(state):
            lane_cards = []
            for order in orders:
                if state == "done" and not self._is_done_visible(order, kds["done_visible_minutes"]):
                    continue

                lines = order.line_ids.filtered(lambda l: l.state == state and l.qty > 0)
                if lines:
                    lane_cards.append({
                        "order": order,
                        "lines": lines,
                        "lane_state": state,
                        "kitchen_number": self._format_kitchen_number(order),
                        "pos_reference": self._format_pos_reference(order),
                    })

            lane_cards.sort(
                key=lambda c: (
                    self._priority_rank(c["order"]),
                    c["order"].created_at or c["order"].last_activity_at,
                    c["order"].id,
                )
            )
            return lane_cards

        values = {
            "kds": kds,
            "lane_new": build_lane("new"),
            "lane_preparing": build_lane("preparing"),
            "lane_ready": build_lane("ready"),
            "lane_done": build_lane("done") if kds["show_done"] else [],
        }
        return values

    @http.route("/kitchen/display", auth="user", type="http")
    def kitchen_display(self):
        values = self._build_display_values()
        return request.render("kds_module.kitchen_display_template", values)

    @http.route("/kitchen/display/grid", auth="user", type="http")
    def kitchen_display_grid(self):
        values = self._build_display_values()
        return request.render("kds_module.kitchen_display_grid", values)

    @http.route("/kitchen/display/line/<int:line_id>/next", auth="user", type="http", methods=["POST"], csrf=False)
    def kitchen_display_line_next(self, line_id, **kwargs):
        line = request.env["kitchen.order.line"].sudo().browse(line_id).exists()
        if line:
            line.action_next_state()

        return request.make_response(
            json.dumps({"ok": True}),
            headers=[("Content-Type", "application/json")],
        )

    @http.route("/kitchen/display/order/<int:order_id>/move/<string:from_state>", auth="user", type="http", methods=["POST"], csrf=False)
    def kitchen_display_order_move(self, order_id, from_state, **kwargs):
        order = request.env["kitchen.order"].sudo().browse(order_id).exists()
        if order:
            order.action_move_lines_from_state(from_state)

        return request.make_response(
            json.dumps({"ok": True}),
            headers=[("Content-Type", "application/json")],
        )
