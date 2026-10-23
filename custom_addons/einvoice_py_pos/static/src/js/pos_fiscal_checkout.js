/** @odoo-module */

import { PaymentScreen } from "@point_of_sale/app/screens/payment_screen/payment_screen";
import { ErrorPopup } from "@point_of_sale/app/errors/popups/error_popup";
import { Order } from "@point_of_sale/app/store/models";
import { SelectionPopup } from "@point_of_sale/app/utils/input_popups/selection_popup";
import { uuidv4 } from "@point_of_sale/utils";
import { _t } from "@web/core/l10n/translation";
import { patch } from "@web/core/utils/patch";


patch(Order.prototype, {
    setup(_defaultObj, options) {
        super.setup(...arguments);
        const json = options?.json || {};
        this.pyFiscalChoice = this.pyFiscalChoice || json.py_fiscal_choice || false;
        this.pyFiscalDecisionId =
            this.pyFiscalDecisionId || json.py_fiscal_decision_id || false;
        this.pyRucResolution = this.pyRucResolution || json.py_ruc_resolution || false;
        this.pyFiscalDelivery = this.pyFiscalDelivery || json.py_fiscal_delivery || false;
        this.pyFiscalEmail = this.pyFiscalEmail || json.py_fiscal_email || false;
    },
    init_from_JSON(json) {
        super.init_from_JSON(...arguments);
        this.pyFiscalChoice = json.py_fiscal_choice || false;
        this.pyFiscalDecisionId = json.py_fiscal_decision_id || false;
        this.pyRucResolution = json.py_ruc_resolution || false;
        this.pyFiscalDelivery = json.py_fiscal_delivery || false;
        this.pyFiscalEmail = json.py_fiscal_email || false;
    },
    export_as_JSON() {
        return {
            ...super.export_as_JSON(...arguments),
            py_fiscal_choice: this.pyFiscalChoice || false,
            py_fiscal_decision_id: this.pyFiscalDecisionId || false,
            py_ruc_resolution: this.pyRucResolution || false,
            py_fiscal_delivery: this.pyFiscalDelivery || false,
            py_fiscal_email: this.pyFiscalEmail || false,
        };
    },
    setPyFiscalDecision({ choice, partner, rucResolution, delivery, email }) {
        this.pyFiscalChoice = choice;
        this.pyFiscalDecisionId = this.pyFiscalDecisionId || uuidv4();
        this.pyRucResolution = rucResolution;
        this.pyFiscalDelivery = delivery;
        this.pyFiscalEmail = email || false;
        this.set_partner(partner || null);
        this.set_to_invoice(choice !== "no_fe");
    },
});


patch(PaymentScreen.prototype, {
    get pyFiscalChoiceLabel() {
        const labels = {
            no_fe: _t("No FE"),
            consumer_final: _t("Consumer final FE"),
            with_ruc: _t("FE with RUC"),
        };
        return labels[this.currentOrder.pyFiscalChoice] || _t("Select fiscal receipt");
    },
    async validateOrder(isForceValidate) {
        if (
            this.pos.config.py_fiscal_checkout_enabled &&
            !this.currentOrder.pyFiscalChoice &&
            !(await this.selectPyFiscalChoice())
        ) {
            return;
        }
        return super.validateOrder(...arguments);
    },
    async selectPyFiscalChoice() {
        const list = [];
        if (this.pos.config.py_fiscal_allow_no_fe) {
            list.push({
                id: "no_fe",
                label: _t("No electronic invoice"),
                description: _t("Print only the standard non-fiscal POS receipt."),
                item: "no_fe",
                isSelected: this.currentOrder.pyFiscalChoice === "no_fe",
            });
        }
        list.push(
            {
                id: "consumer_final",
                label: _t("Consumer final"),
                description: _t("Issue an unnamed B2C electronic invoice."),
                item: "consumer_final",
                isSelected: this.currentOrder.pyFiscalChoice === "consumer_final",
            },
            {
                id: "with_ruc",
                label: _t("Customer with RUC"),
                description: _t("Use a taxpayer already registered in Odoo."),
                item: "with_ruc",
                isSelected: this.currentOrder.pyFiscalChoice === "with_ruc",
            }
        );
        const { confirmed, payload: choice } = await this.popup.add(SelectionPopup, {
            title: _t("Fiscal receipt"),
            body: _t("Choose what the customer requested before completing payment."),
            list,
        });
        if (!confirmed || !choice) {
            return false;
        }
        if (choice === "no_fe") {
            this.currentOrder.setPyFiscalDecision({
                choice,
                partner: this.currentOrder.get_partner(),
                rucResolution: "not_applicable",
                delivery: "not_applicable",
                email: false,
            });
            return true;
        }
        if (choice === "consumer_final") {
            const partner = this.pos.db.get_partner_by_id(
                this.pos.config.py_fiscal_unnamed_partner_id?.[0] ||
                    this.pos.config.py_fiscal_unnamed_partner_id
            );
            if (!partner) {
                await this.popup.add(ErrorPopup, {
                    title: _t("Fiscal configuration incomplete"),
                    body: _t("The configured unnamed consumer is not available in this POS."),
                });
                return false;
            }
            this.currentOrder.setPyFiscalDecision({
                choice,
                partner,
                rucResolution: "not_applicable",
                delivery: "print",
                email: false,
            });
            return true;
        }
        let partner = this.currentOrder.get_partner();
        if (partner?.py_sifen_receiver_profile !== "taxpayer") {
            await this.selectPartner(false, []);
            partner = this.currentOrder.get_partner();
        }
        if (partner?.py_sifen_receiver_profile !== "taxpayer" || !partner.vat) {
            await this.popup.add(ErrorPopup, {
                title: _t("Taxpayer required"),
                body: _t("Select a locally registered customer with a Paraguay taxpayer profile and RUC."),
            });
            return false;
        }
        this.currentOrder.setPyFiscalDecision({
            choice,
            partner,
            rucResolution: "local",
            delivery: partner.email ? "email" : "print",
            email: partner.email || false,
        });
        return true;
    },
});
