/** @odoo-module **/
import publicWidget from "@web/legacy/js/public/public_widget";
import { jsonrpc } from "@web/core/network/rpc_service";

publicWidget.registry.EjadRop = publicWidget.Widget.extend({
    selector: ".ejad-rop",
    events: {
        "click .ejad-update": "openUpdate",
        "click .ejad-cancel": "closeUpdate",
        "submit .ejad-adjust-form": "applyUpdate",
        "click .ejad-next": "nextPage",
        "click .ejad-previous": "previousPage",
    },
    async start() {
        await this._super(...arguments);
        this.offset = 0;
        this.limit = 24;
        this.stopped = false;
        this.dialog = this.el.querySelector("dialog");
        await this.refresh();
    },
    destroy() {
        this.stopped = true;
        clearTimeout(this.timer);
        this.abortController?.abort();
        this._super(...arguments);
    },
    async refresh() {
        clearTimeout(this.timer);
        this.abortController?.abort();
        this.abortController = new AbortController();
        const signal = this.abortController.signal;
        try {
            const query = new URLSearchParams({comparison: this.el.dataset.comparison, limit: this.limit, offset: this.offset});
            const response = await fetch(`/ejad/rop/products?${query}`, {credentials: "same-origin", cache: "no-store", signal});
            if (!response.ok || !response.headers.get("content-type")?.includes("application/json")) throw new Error("Stock is unavailable. Check your login and access rights.");
            const data = await response.json();
            this.renderProducts(data.products);
            this.el.querySelector(".ejad-status").textContent = data.products.length ? `Updated ${new Date().toLocaleTimeString()}` : "No products match this stock level.";
            this.el.querySelector(".ejad-previous").disabled = this.offset === 0;
            this.el.querySelector(".ejad-next").disabled = !data.has_more;
        } catch (error) {
            if (error.name !== "AbortError") this.el.querySelector(".ejad-status").textContent = error.message;
        } finally {
            if (!signal.aborted && !this.stopped && this.el.dataset.comparison === ">") {
                this.timer = setTimeout(() => {
                    if (!document.hidden && !this.dialog.open) this.refresh();
                    else this.timer = setTimeout(() => this.refresh(), 3000);
                }, 3000);
            }
        }
    },
    renderProducts(products) {
        const container = this.el.querySelector(".ejad-products");
        container.replaceChildren();
        for (const product of products) {
            const column = document.createElement("div");
            column.className = "col-sm-6 col-lg-4 col-xl-3";
            const card = document.createElement("article");
            card.className = "card h-100 p-3";
            const image = document.createElement("img");
            image.src = product.image_url;
            image.alt = product.name;
            image.height = 160;
            image.className = "object-fit-contain mb-3";
            card.append(image);
            if (this.el.dataset.adjust === "1") {
                const button = document.createElement("button");
                button.className = "btn btn-outline-primary ejad-update mb-3";
                button.textContent = "Update Product quantity";
                button.dataset.id = product.id;
                button.dataset.name = product.name;
                button.dataset.quantity = product.quantity;
                card.append(button);
            }
            const name = document.createElement("h2");
            name.className = "h6";
            name.textContent = product.name;
            const quantity = document.createElement("p");
            quantity.textContent = `On hand: ${product.quantity}`;
            card.append(name, quantity);
            column.append(card);
            container.append(column);
        }
    },
    openUpdate(event) {
        const data = event.currentTarget.dataset;
        this.productId = Number(data.id);
        this.dialog.querySelector(".ejad-product-name").textContent = data.name;
        this.dialog.querySelector("input").value = Number.isInteger(Number(data.quantity)) ? data.quantity : "";
        this.dialog.querySelector(".ejad-adjust-error").textContent = "";
        this.dialog.showModal();
    },
    closeUpdate() { this.dialog.close(); },
    async applyUpdate(event) {
        event.preventDefault();
        const button = this.dialog.querySelector("button[type=submit]");
        if (button.disabled) return;
        button.disabled = true;
        try {
            await jsonrpc("/ejad/rop/update", {product_id: this.productId, quantity: Number(this.dialog.querySelector("input").value)});
            this.dialog.close();
            await this.refresh();
        } catch (error) {
            this.dialog.querySelector(".ejad-adjust-error").textContent = error.data?.message || error.message;
        } finally { button.disabled = false; }
    },
    nextPage() { this.offset += this.limit; return this.refresh(); },
    previousPage() { this.offset = Math.max(0, this.offset - this.limit); return this.refresh(); },
});
