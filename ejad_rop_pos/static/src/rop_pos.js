/** @odoo-module **/
import { Component, onMounted, useState } from "@odoo/owl";
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { usePos } from "@point_of_sale/app/store/pos_hook";
import { useService } from "@web/core/utils/hooks";
import { Order } from "@point_of_sale/app/store/models";
import { ProductScreen } from "@point_of_sale/app/screens/product_screen/product_screen";
import { PaymentScreen } from "@point_of_sale/app/screens/payment_screen/payment_screen";
import { ErrorPopup } from "@point_of_sale/app/errors/popups/error_popup";
import { OrderReceipt } from "@point_of_sale/app/screens/receipt_screen/receipt/order_receipt";

async function checkStock(order) {
    try {
        const result = await order.env.services.orm.call("pos.session", "ejad_check_stock", [
            [order.pos.pos_session.id],
            order.get_orderlines().map(line => ({product_id: line.get_product().id, qty: line.get_quantity()})),
        ]);
        if (!result.ok) {
            await order.env.services.popup.add(ErrorPopup, {
                title: _t("Re-Order Point"),
                body: result.message + "\n" + result.products.map(p => `${p.name}: ${p.quantity}`).join("\n"),
            });
        }
        return result.ok;
    } catch (error) {
        await order.env.services.popup.add(ErrorPopup, {
            title: _t("Stock check unavailable"),
            body: _t("Connect to the server to verify current stock before payment."),
        });
        return false;
    }
}

function customerError(partner) {
    if (!partner) return _t("Select a customer before validating payment.");
    const phone = (partner.phone || "").trim();
    if (!phone) return _t("The customer must have a phone number.");
    if (!phone.startsWith("+2")) return _t("The customer phone number must start with +2.");
    return null;
}

patch(Order.prototype, {
    async pay() {
        if (this.canPay() && await checkStock(this)) {
            return super.pay(...arguments);
        }
    },
});

patch(PaymentScreen.prototype, {
    onMounted() {
        // Cash now has already added its exact cash amount. The native single-
        // method shortcut would otherwise add an extra zero-amount cash line.
        if (!this.currentOrder.ejadCashNow) return super.onMounted(...arguments);
    },
    setup() {
        super.setup(...arguments);
        onMounted(() => {
            if (this.currentOrder.ejadCashNow && !this.currentOrder.finalized) {
                this.validateOrder(false);
            }
        });
    },
    async _isOrderValid() {
        const error = customerError(this.currentOrder.get_partner());
        if (error) {
            await this.popup.add(ErrorPopup, {title: _t("Customer required"), body: error});
            return false;
        }
        if (!await checkStock(this.currentOrder)) return false;
        return super._isOrderValid(...arguments);
    },
    async afterOrderValidation() {
        const order = this.currentOrder;
        if (order.ejadCashNow && !this.pos.config.iface_print_auto && !order._printed) {
            const printed = await this.printer.print(OrderReceipt, {
                data: order.export_for_printing(), formatCurrency: this.env.utils.formatCurrency,
            }, {webPrintFallback: true});
            order._printed = Boolean(printed);
        }
        return super.afterOrderValidation(...arguments);
    },
});

export class CashNowButton extends Component {
    static template = "ejad_rop_pos.CashNowButton";
    setup() {
        this.pos = usePos();
        this.orm = useService("orm");
        this.popup = useService("popup");
        this.state = useState({busy: false});
    }
    async onClick() {
        if (this.state.busy) return;
        this.state.busy = true;
        try {
            const order = this.pos.get_order();
            if (!order.canPay()) return;
            const method = this.pos.payment_methods.find(m => m.is_cash_count && this.pos.config.payment_method_ids.includes(m.id));
            const partnerId = this.pos.config.ejad_cash_partner_id?.[0];
            const partner = this.pos.db.get_partner_by_id(partnerId);
            const error = !method ? _t("Configure a cash payment method first.") : customerError(partner);
            if (error) {
                await this.popup.add(ErrorPopup, {title: _t("Cash now setup"), body: error});
                return;
            }
            if (order.get_paymentlines().some(line => line.get_amount() || line.payment_status)) {
                await this.popup.add(ErrorPopup, {title: _t("Payment already started"), body: _t("Finish or remove existing payments before using Cash now.")});
                return;
            }
            if (order.get_orderlines().some(line => line.get_product().tracking !== "none" && !line.has_valid_product_lot())) {
                await this.popup.add(ErrorPopup, {title: _t("Tracking required"), body: _t("Enter lot or serial numbers before using Cash now.")});
                return;
            }
            if (!await checkStock(order)) return;
            order.set_partner(partner);
            order.set_to_invoice(true);
            for (const line of [...order.get_paymentlines()]) order.remove_paymentline(line);
            const due = order.get_due();
            const result = order.add_paymentline(method);
            if (!result) return;
            order.selected_paymentline.set_amount(due);
            order.ejadCashNow = true;
            this.pos.showScreen("PaymentScreen");
        } finally {
            this.state.busy = false;
        }
    }
}
ProductScreen.addControlButton({component: CashNowButton});
