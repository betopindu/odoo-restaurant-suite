/** @odoo-module */

import { Order } from "@point_of_sale/app/store/models";
import { PosStore } from "@point_of_sale/app/store/pos_store";
import { ProductScreen } from "@point_of_sale/app/screens/product_screen/product_screen";
import { patch } from "@web/core/utils/patch";

patch(Order.prototype, {
    setup(_defaultObj, options) {
        super.setup(...arguments);
        this.kdsPreparationRevision = Number(
            this.kdsPreparationRevision || options?.json?.kds_preparation_revision || 0
        );
    },
    init_from_JSON(json) {
        super.init_from_JSON(...arguments);
        this.kdsPreparationRevision = Number(json.kds_preparation_revision || 0);
    },
    export_as_JSON() {
        return {
            ...super.export_as_JSON(...arguments),
            kds_preparation_revision: this.kdsPreparationRevision || 0,
        };
    },
});

patch(PosStore.prototype, {
    async sendOrderInPreparationUpdateLastChange(order, cancelled = false) {
        const changes = order.changesToOrder(cancelled);
        if (changes.new.length || changes.cancelled.length) {
            order.kdsPreparationRevision = (order.kdsPreparationRevision || 0) + 1;
        }
        return super.sendOrderInPreparationUpdateLastChange(...arguments);
    },
});

patch(ProductScreen.prototype, {
    get swapButton() {
        // The KDS is itself a preparation destination. Odoo's standard
        // restaurant UI otherwise hides "Order" when no physical printer is
        // configured, even though getOrderChanges() can track every product.
        return this.pos.config.module_pos_restaurant;
    },
});
