/** @odoo-module */

import { PaymentScreen } from "@point_of_sale/app/screens/payment_screen/payment_screen";
import { ReceiptScreen } from "@point_of_sale/app/screens/receipt_screen/receipt_screen";
import { ErrorPopup } from "@point_of_sale/app/errors/popups/error_popup";
import { Order } from "@point_of_sale/app/store/models";
import { SelectionPopup } from "@point_of_sale/app/utils/input_popups/selection_popup";
import { TextInputPopup } from "@point_of_sale/app/utils/input_popups/text_input_popup";
import { jsonrpc } from "@web/core/network/rpc_service";
import { uuidv4 } from "@point_of_sale/utils";
import { _t } from "@web/core/l10n/translation";
import { patch } from "@web/core/utils/patch";
import { onMounted, onWillUnmount, useState } from "@odoo/owl";


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
        const partner = await this.resolvePyTaxpayer();
        if (!partner) {
            return false;
        }
        if (partner.py_sifen_receiver_profile !== "taxpayer" || !partner.vat) {
            await this.popup.add(ErrorPopup, {
                title: _t("Taxpayer required"),
                body: _t("The resolved customer does not have a valid Paraguay taxpayer profile."),
            });
            return false;
        }
        this.currentOrder.setPyFiscalDecision({
            choice,
            partner,
            rucResolution: partner.py_sifen_ruc_resolution || "local",
            delivery: partner.email ? "email" : "print",
            email: partner.email || false,
        });
        return true;
    },
    async resolvePyTaxpayer() {
        const current = this.currentOrder.get_partner();
        const { confirmed, payload: ruc } = await this.popup.add(TextInputPopup, {
            title: _t("Customer RUC"),
            body: _t("Enter the Paraguay RUC including its verification digit."),
            startingValue: current?.vat || "",
            placeholder: "80012345-6",
        });
        if (!confirmed || !ruc) {
            return false;
        }
        let result;
        try {
            result = await jsonrpc("/einvoice_py_pos/ruc/resolve", {
                session_id: this.pos.pos_session.id,
                ruc,
            });
        } catch (_error) {
            await this.popup.add(ErrorPopup, {
                title: _t("RUC lookup failed"),
                body: _t("The RUC could not be resolved. No fiscal document was created."),
            });
            return false;
        }
        if (result.status === "found") {
            return this.completePyTaxpayer(result);
        }
        return this.createManualPyTaxpayer(result.ruc || ruc, result.reason);
    },
    async completePyTaxpayer(result) {
        let taxpayerType = result.taxpayer_type;
        if (!taxpayerType) {
            taxpayerType = await this.selectPyTaxpayerType();
            if (!taxpayerType) {
                return false;
            }
            result = await jsonrpc("/einvoice_py_pos/ruc/complete", {
                session_id: this.pos.pos_session.id,
                partner_id: result.partner_id,
                taxpayer_type: taxpayerType,
            });
        }
        if (!result.partner) {
            return false;
        }
        this.pos.db.add_partners([result.partner]);
        return this.pos.db.get_partner_by_id(result.partner_id);
    },
    async createManualPyTaxpayer(ruc, reason) {
        const reasonText =
            reason === "authority_not_found"
                ? _t("SIFEN did not find this RUC. Verify it before continuing manually.")
                : _t("SIFEN Consulta RUC is unavailable. Manual data will be marked unverified.");
        const { confirmed, payload: name } = await this.popup.add(TextInputPopup, {
            title: _t("Manual taxpayer entry"),
            body: reasonText,
            placeholder: _t("Customer legal name"),
        });
        if (!confirmed || !name) {
            return false;
        }
        const taxpayerType = await this.selectPyTaxpayerType();
        if (!taxpayerType) {
            return false;
        }
        const emailResult = await this.popup.add(TextInputPopup, {
            title: _t("Delivery email (optional)"),
            body: _t("Without an email, the accepted KuDE will be printed instead."),
            placeholder: "customer@example.com",
        });
        if (!emailResult.confirmed) {
            return false;
        }
        let result;
        try {
            result = await jsonrpc("/einvoice_py_pos/ruc/manual", {
                session_id: this.pos.pos_session.id,
                ruc,
                name,
                taxpayer_type: taxpayerType,
                email: emailResult.payload || "",
            });
        } catch (_error) {
            await this.popup.add(ErrorPopup, {
                title: _t("Customer could not be saved"),
                body: _t("Review the RUC and customer data, then try again."),
            });
            return false;
        }
        this.pos.db.add_partners([result.partner]);
        return this.pos.db.get_partner_by_id(result.partner_id);
    },
    async selectPyTaxpayerType() {
        const { confirmed, payload } = await this.popup.add(SelectionPopup, {
            title: _t("Taxpayer type"),
            list: [
                { id: "1", label: _t("Physical person"), item: "1" },
                { id: "2", label: _t("Legal entity"), item: "2" },
            ],
        });
        return confirmed ? payload : false;
    },
});


patch(ReceiptScreen.prototype, {
    setup() {
        super.setup(...arguments);
        this.pyFiscalStatus = useState({
            status: this.currentOrder.pyFiscalChoice === "no_fe" ? "not_applicable" : "loading",
            message: "",
            authority_code: "",
            authority_protocol: "",
            cdc: "",
            delivery_ready: false,
            email_status: "not_requested",
            email_available: false,
        });
        this.pyFiscalPoll = null;
        onMounted(() => this.startPyFiscalStatusPolling());
        onWillUnmount(() => this.stopPyFiscalStatusPolling());
    },
    get showPyFiscalStatus() {
        return Boolean(
            this.pos.config.py_fiscal_checkout_enabled &&
            this.currentOrder.pyFiscalChoice &&
            this.currentOrder.pyFiscalChoice !== "no_fe"
        );
    },
    get pyFiscalStatusLabel() {
        const labels = {
            loading: _t("Checking fiscal status"),
            queued: _t("Queued for SIFEN"),
            processing: _t("Sending to SIFEN"),
            accepted: _t("Accepted by SIFEN"),
            rejected: _t("Rejected by SIFEN"),
            recovery_required: _t("Recovery required"),
            operator_review: _t("Operator review required"),
            operator_submission_required: _t("Operator submission required"),
        };
        return labels[this.pyFiscalStatus.status] || _t("Fiscal status unavailable");
    },
    get pyFiscalStatusClass() {
        if (this.pyFiscalStatus.status === "accepted") {
            return "alert-success";
        }
        if (this.pyFiscalStatus.status === "rejected") {
            return "alert-danger";
        }
        if (["recovery_required", "operator_review"].includes(this.pyFiscalStatus.status)) {
            return "alert-warning";
        }
        return "alert-info";
    },
    get pyFiscalStatusIcon() {
        if (this.pyFiscalStatus.status === "accepted") {
            return "fa-check-circle";
        }
        if (this.pyFiscalStatus.status === "rejected") {
            return "fa-times-circle";
        }
        if (["recovery_required", "operator_review"].includes(this.pyFiscalStatus.status)) {
            return "fa-exclamation-triangle";
        }
        if (["loading", "queued", "processing"].includes(this.pyFiscalStatus.status)) {
            return "fa-circle-o-notch fa-spin";
        }
        return "fa-info-circle";
    },
    async startPyFiscalStatusPolling() {
        if (!this.showPyFiscalStatus) {
            return;
        }
        await this.refreshPyFiscalStatus();
        if (["loading", "queued", "processing"].includes(this.pyFiscalStatus.status)) {
            this.pyFiscalPoll = setInterval(() => this.refreshPyFiscalStatus(), 2000);
        }
    },
    stopPyFiscalStatusPolling() {
        if (this.pyFiscalPoll) {
            clearInterval(this.pyFiscalPoll);
            this.pyFiscalPoll = null;
        }
    },
    async refreshPyFiscalStatus() {
        try {
            const result = await jsonrpc("/einvoice_py_pos/fiscal/status", {
                session_id: this.pos.pos_session.id,
                decision_id: this.currentOrder.pyFiscalDecisionId,
            });
            Object.assign(this.pyFiscalStatus, result);
            if (!["loading", "queued", "processing"].includes(result.status)) {
                this.stopPyFiscalStatusPolling();
            }
        } catch (_error) {
            Object.assign(this.pyFiscalStatus, {
                status: "operator_review",
                message: _t("Fiscal status could not be loaded. Ask an authorized operator to review it."),
            });
            this.stopPyFiscalStatusPolling();
        }
    },
    openPyAuthoritativeFile(fileKind) {
        const decision = encodeURIComponent(this.currentOrder.pyFiscalDecisionId);
        const session = encodeURIComponent(this.pos.pos_session.id);
        window.open(
            `/einvoice_py_pos/fiscal/file/${decision}/${fileKind}?session_id=${session}`,
            "_blank",
            "noopener"
        );
    },
    async resendPyFiscalEmail() {
        if (this.pyFiscalStatus.emailSending) {
            return;
        }
        this.pyFiscalStatus.emailSending = true;
        const requestId = uuidv4();
        try {
            const result = await jsonrpc("/einvoice_py_pos/fiscal/email", {
                session_id: this.pos.pos_session.id,
                decision_id: this.currentOrder.pyFiscalDecisionId,
                request_id: requestId,
            });
            this.pyFiscalStatus.email_status = result.status;
            this.pyFiscalStatus.message = _t("The authoritative KuDE and XML email was queued.");
        } catch (_error) {
            this.pyFiscalStatus.email_status = "failed";
            this.pyFiscalStatus.message = _t("Email could not be queued. Ask a fiscal operator to review it.");
        } finally {
            this.pyFiscalStatus.emailSending = false;
        }
    },
});
