let deliverySettings = { free_delivery_min: 500, delivery_charge: 150 };
let latestCartQuote = null;
const ANALYTICS_CONSENT_KEY = "auraAnalyticsConsent";

fetch("/store/api/delivery-settings/")
    .then((response) => response.json())
    .then((data) => {
        deliverySettings = data;
    })
    .catch(() => {});

function getCsrfToken() {
    const match = document.cookie.match(/csrftoken=([^;]+)/);
    return match ? decodeURIComponent(match[1]) : "";
}

function analyticsConsentGranted() {
    return localStorage.getItem(ANALYTICS_CONSENT_KEY) === "granted";
}

function loadAnalyticsIfAllowed() {
    const measurementId = document.body ? document.body.dataset.analyticsId : "";
    if (!measurementId || !analyticsConsentGranted() || window.auraAnalyticsLoaded) {
        return;
    }
    window.auraAnalyticsLoaded = true;
    window.dataLayer = window.dataLayer || [];
    window.gtag = function gtag() {
        window.dataLayer.push(arguments);
    };
    window.gtag("js", new Date());
    window.gtag("config", measurementId, {
        anonymize_ip: true,
        send_page_view: true,
    });
    const script = document.createElement("script");
    script.async = true;
    script.src = `https://www.googletagmanager.com/gtag/js?id=${encodeURIComponent(measurementId)}`;
    document.head.appendChild(script);
}

function analyticsEvent(name, params = {}) {
    if (analyticsConsentGranted() && typeof window.gtag !== "function") {
        loadAnalyticsIfAllowed();
    }
    if (!analyticsConsentGranted() || typeof window.gtag !== "function") {
        return;
    }
    const safeParams = {};
    Object.entries(params || {}).forEach(([key, value]) => {
        if (/email|phone|address|name|reference|order/i.test(key)) {
            return;
        }
        if (value == null) {
            return;
        }
        safeParams[key] = value;
    });
    window.gtag("event", name, safeParams);
}

function trackCurrentPageAnalytics() {
    const productView = document.querySelector("[data-analytics-product-view]");
    if (productView && productView.dataset.analyticsTracked !== "1") {
        productView.dataset.analyticsTracked = "1";
        analyticsEvent("view_item", {
            currency: "PKR",
            value: Number(productView.dataset.price || 0),
            product_id: productView.dataset.productId || "",
            in_stock: productView.dataset.inStock === "1",
        });
    }

    const purchase = document.querySelector("[data-analytics-purchase]");
    if (purchase && purchase.dataset.analyticsTracked !== "1") {
        purchase.dataset.analyticsTracked = "1";
        analyticsEvent("purchase", {
            currency: "PKR",
            value: Number(purchase.dataset.value || 0),
            item_count: Number(purchase.dataset.itemCount || 0),
        });
    }
}

function ensureAnalyticsConsentBanner() {
    const measurementId = document.body ? document.body.dataset.analyticsId : "";
    if (!measurementId || localStorage.getItem(ANALYTICS_CONSENT_KEY)) {
        loadAnalyticsIfAllowed();
        return;
    }
    const banner = document.createElement("div");
    banner.className = "cookie-consent-banner";
    banner.setAttribute("role", "dialog");
    banner.setAttribute("aria-live", "polite");

    const text = document.createElement("p");
    text.textContent = "Aura Foods uses optional analytics only with your consent. Necessary cart and security cookies remain active.";
    banner.appendChild(text);

    const actions = document.createElement("div");
    actions.className = "cookie-consent-actions";
    const accept = document.createElement("button");
    accept.type = "button";
    accept.textContent = "Allow analytics";
    const decline = document.createElement("button");
    decline.type = "button";
    decline.textContent = "Necessary only";
    actions.appendChild(accept);
    actions.appendChild(decline);
    banner.appendChild(actions);
    document.body.appendChild(banner);

    accept.addEventListener("click", () => {
        localStorage.setItem(ANALYTICS_CONSENT_KEY, "granted");
        banner.remove();
        loadAnalyticsIfAllowed();
        trackCurrentPageAnalytics();
    });
    decline.addEventListener("click", () => {
        localStorage.setItem(ANALYTICS_CONSENT_KEY, "denied");
        banner.remove();
    });
}

function escapeHtml(value) {
    return String(value || "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#39;");
}

function formatMoney(value) {
    return Number(value || 0).toLocaleString(undefined, {
        minimumFractionDigits: 0,
        maximumFractionDigits: 2,
    });
}

function normalizeCart(rawCart) {
    return (rawCart || [])
        .filter((item) => item && item.variantId && item.qty)
        .map((item) => ({
            variantId: String(item.variantId),
            productId: String(item.productId || ""),
            name: String(item.name || ""),
            unitPrice: Number(item.unitPrice || item.price || 0),
            image: String(item.image || ""),
            weight: String(item.weight || ""),
            qty: Math.max(1, Number(item.qty || 1)),
        }));
}

let cart = normalizeCart(JSON.parse(localStorage.getItem("auraCart") || "[]"));

function persistCart() {
    localStorage.setItem("auraCart", JSON.stringify(cart));
    updateCartCount();
}

function updateCartCount() {
    const count = cart.reduce((sum, item) => sum + item.qty, 0);
    document.querySelectorAll("#cartCount").forEach((el) => {
        el.textContent = count;
    });
}

function addToCart(variantId, name, price, image, weight, productId) {
    const existing = cart.find((item) => item.variantId === String(variantId));
    if (existing) {
        existing.qty += 1;
    } else {
        cart.push({
            variantId: String(variantId),
            productId: String(productId || ""),
            name: String(name || ""),
            unitPrice: Number(price || 0),
            image: String(image || ""),
            weight: String(weight || ""),
            qty: 1,
        });
    }
    persistCart();
    showToast(`${name} added to cart!`);
    analyticsEvent("add_to_cart", {
        currency: "PKR",
        value: Number(price || 0),
        product_id: String(productId || ""),
        variant_id: String(variantId || ""),
        quantity: 1,
    });
    renderCart();
}

function removeFromCart(variantId) {
    cart = cart.filter((item) => item.variantId !== String(variantId));
    latestCartQuote = null;
    persistCart();
    renderCart();
}

function updateQty(variantId, delta) {
    const item = cart.find((cartItem) => cartItem.variantId === String(variantId));
    if (!item) {
        return;
    }
    item.qty = Math.max(1, item.qty + delta);
    latestCartQuote = null;
    persistCart();
    renderCart();
}

function buildCheckoutPayload() {
    return cart.map((item) => ({
        variant_id: item.variantId,
        qty: item.qty,
    }));
}

function currentCheckoutCity() {
    const cityInput = document.getElementById("city");
    return cityInput ? cityInput.value.trim() : "";
}

async function quoteCart() {
    if (cart.length === 0) {
        latestCartQuote = { ok: false, errors: [{ message: "Your cart is empty." }] };
        return latestCartQuote;
    }

    const response = await fetch("/store/api/cart/quote/", {
        method: "POST",
        credentials: "same-origin",
        headers: {
            "Content-Type": "application/json",
            "X-CSRFToken": getCsrfToken(),
        },
        body: JSON.stringify({ items: buildCheckoutPayload(), city: currentCheckoutCity() }),
    });
    const data = await response.json();
    latestCartQuote = data;

    if (data.ok) {
        cart = data.lines.map((line) => ({
            variantId: String(line.variant_id),
            productId: "",
            name: line.product_name,
            unitPrice: Number(line.unit_price),
            image: line.image || "",
            weight: line.variant_label || "",
            qty: Number(line.quantity || 1),
        }));
        persistCart();
    }

    return data;
}

function setCheckoutEnabled(enabled) {
    const checkoutBtn = document.getElementById("checkoutBtn");
    if (!checkoutBtn) {
        return;
    }
    checkoutBtn.toggleAttribute("aria-disabled", !enabled);
    checkoutBtn.style.pointerEvents = enabled ? "" : "none";
    checkoutBtn.style.opacity = enabled ? "" : "0.55";
}

function renderQuoteError(message) {
    const summary = document.getElementById("cartSummary");
    if (!summary) {
        showToast(message);
        return;
    }
    let error = document.getElementById("cartQuoteError");
    if (!error) {
        error = document.createElement("p");
        error.id = "cartQuoteError";
        error.style.cssText = "color:#c0392b;text-align:center;font-size:.875rem;margin-top:.75rem";
        summary.appendChild(error);
    }
    error.textContent = message;
}

function createTextElement(tag, className, text) {
    const element = document.createElement(tag);
    if (className) {
        element.className = className;
    }
    element.textContent = text == null ? "" : String(text);
    return element;
}

function createCartButton(label, className, onClick) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = label;
    if (className) {
        button.className = className;
    }
    button.addEventListener("click", onClick);
    return button;
}

function renderCartLine(container, item, isFallback) {
    const row = document.createElement("div");
    row.className = "cart-item fade-in";

    const img = document.createElement("img");
    img.src = item.image || "/static/images/hero-spices.jpg";
    img.alt = item.product_name || item.name || "Cart item";
    img.className = "cart-item-img";
    img.loading = "lazy";
    row.appendChild(img);

    const info = document.createElement("div");
    info.className = "cart-item-info";
    info.appendChild(createTextElement("div", "cart-item-name", item.product_name || item.name || "Unavailable item"));
    info.appendChild(createTextElement("div", "cart-item-price", isFallback ? "Needs refresh" : `Rs.${formatMoney(item.unit_price)}`));

    const qty = document.createElement("div");
    qty.className = "cart-item-qty";
    if (!isFallback) {
        qty.appendChild(createCartButton("-", "qty-btn", () => updateQty(item.variant_id, -1)));
    }
    qty.appendChild(createTextElement("span", "qty-value", item.quantity || item.qty));
    if (!isFallback) {
        qty.appendChild(createCartButton("+", "qty-btn", () => updateQty(item.variant_id, 1)));
    }
    const remove = createCartButton("Remove", "", () => removeFromCart(item.variant_id || item.variantId));
    remove.style.cssText = "margin-left:1rem;background:none;border:none;color:#c0392b;cursor:pointer;font-size:.8125rem";
    qty.appendChild(remove);
    info.appendChild(qty);

    if (!isFallback) {
        info.appendChild(createTextElement("div", "cart-item-weight", item.variant_label));
    }
    row.appendChild(info);
    container.appendChild(row);
}

async function renderCart() {
    const container = document.getElementById("cartItems");
    const summary = document.getElementById("cartSummary");
    const empty = document.getElementById("emptyCart");
    if (!container) {
        return;
    }

    if (cart.length === 0) {
        if (empty) empty.style.display = "block";
        container.style.display = "none";
        if (summary) summary.style.display = "none";
        setCheckoutEnabled(false);
        return;
    }

    if (empty) empty.style.display = "none";
    container.style.display = "flex";
    if (summary) summary.style.display = "block";
    container.replaceChildren();
    const loading = createTextElement("div", "", "Checking current prices and stock...");
    loading.style.cssText = "padding:1rem;color:var(--muted)";
    container.appendChild(loading);
    setCheckoutEnabled(false);

    let quote;
    try {
        quote = await quoteCart();
    } catch (error) {
        renderQuoteError("We could not refresh your cart. Please try again.");
        return;
    }

    if (!quote.ok) {
        const message = (quote.errors && quote.errors[0] && quote.errors[0].message) || "Please review your cart.";
        renderQuoteError(message);
        container.replaceChildren();
        cart.forEach((item) => renderCartLine(container, item, true));
        return;
    }

    const oldError = document.getElementById("cartQuoteError");
    if (oldError) oldError.remove();

    container.replaceChildren();
    quote.lines.forEach((item) => renderCartLine(container, item, false));

    document.getElementById("cartSubtotal").textContent = `Rs.${formatMoney(quote.subtotal)}`;
    document.getElementById("cartDelivery").textContent = Number(quote.delivery_charge) === 0 ? "Free" : `Rs.${formatMoney(quote.delivery_charge)}`;
    document.getElementById("cartTotal").textContent = `Rs.${formatMoney(quote.grand_total)}`;

    const freeNote = document.getElementById("freeDeliveryNote");
    if (freeNote) {
        freeNote.textContent = `Free delivery on orders above Rs.${formatMoney(quote.free_delivery_threshold || deliverySettings.free_delivery_min)}`;
    }
    setCheckoutEnabled(true);
}

function handleCheckout(e) {
    e.preventDefault();
    const form = e.target;
    if (form.dataset.submitting === "1") {
        return false;
    }
    const currentCart = JSON.parse(localStorage.getItem("auraCart") || "[]");
    if (currentCart.length === 0) {
        showToast("Your cart is empty!");
        return false;
    }
    if (typeof buildCheckoutPayload !== "function" || typeof quoteCart !== "function") {
        showToast("Cart data is unavailable. Please refresh and try again.");
        return false;
    }
    form.dataset.submitting = "1";
    const submitBtn = form.querySelector('button[type="submit"]');
    if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.textContent = "Checking cart...";
    }
    quoteCart().then((quote) => {
        if (!quote.ok) {
            const message = quote.errors && quote.errors[0] ? quote.errors[0].message : "Please review your cart.";
            showToast(message);
            form.dataset.submitting = "";
            if (submitBtn) {
                submitBtn.disabled = false;
                submitBtn.textContent = "Place Order";
            }
            return;
        }
        const keyField = document.getElementById("idempotencyKey");
        let storedKey = sessionStorage.getItem("auraCheckoutKey");
        if (!storedKey) {
            storedKey = (window.crypto && window.crypto.randomUUID) ? window.crypto.randomUUID() : `checkout-${Date.now()}-${Math.random().toString(16).slice(2)}`;
            sessionStorage.setItem("auraCheckoutKey", storedKey);
        }
        keyField.value = storedKey;
        document.getElementById("cartData").value = JSON.stringify(buildCheckoutPayload());
        analyticsEvent("begin_checkout", {
            currency: "PKR",
            value: Number(quote.grand_total || 0),
            item_count: cart.reduce((sum, item) => sum + Number(item.qty || 0), 0),
        });
        HTMLFormElement.prototype.submit.call(form);
    }).catch(() => {
        showToast("We could not verify your cart. Please try again.");
        form.dataset.submitting = "";
        if (submitBtn) {
            submitBtn.disabled = false;
            submitBtn.textContent = "Place Order";
        }
    });
    return false;
}

document.addEventListener("DOMContentLoaded", () => {
    if (document.querySelector("[data-clear-checkout-storage='1']")) {
        localStorage.removeItem("auraCart");
        sessionStorage.removeItem("auraCheckoutKey");
    }
    if (document.getElementById("cartItems")) {
        renderCart();
    }
    const checkoutForm = document.getElementById("checkoutForm");
    if (checkoutForm) {
        checkoutForm.addEventListener("submit", handleCheckout);
    }
    document.querySelectorAll(".payment-option").forEach((option) => {
        option.addEventListener("click", function () {
            document.querySelectorAll(".payment-option").forEach((other) => other.classList.remove("active"));
            this.classList.add("active");
            const input = this.querySelector('input[type="radio"]');
            if (input) {
                input.checked = true;
            }
        });
    });

    trackCurrentPageAnalytics();
});

function showToast(message) {
    let toast = document.getElementById("toast");
    if (!toast) {
        toast = document.createElement("div");
        toast.id = "toast";
        toast.className = "toast";
        document.body.appendChild(toast);
    }
    toast.textContent = message;
    toast.classList.add("show");
    clearTimeout(toast._timeout);
    toast._timeout = setTimeout(() => toast.classList.remove("show"), 2500);
}

function toggleMenu() {
    document.querySelector(".nav-links").classList.toggle("active");
}

function ratingCsrfToken() {
    const match = document.cookie.match(/(?:^|; )csrftoken=([^;]+)/);
    return match ? decodeURIComponent(match[1]) : "";
}

function rate(n) {
    const buttons = document.querySelectorAll(".star-btn");
    buttons.forEach((b) => (b.disabled = true));
    const body = new URLSearchParams();
    body.set("rating", n);
    fetch("/site-rating/", {
        method: "POST",
        body,
        credentials: "same-origin",
        headers: {"X-CSRFToken": ratingCsrfToken()},
    })
        .then(async (response) => {
            if (response.ok) {
                location.reload();
                return;
            }
            let detail = "Could not submit rating.";
            try {
                const data = await response.json();
                if (data && data.detail) detail = data.detail;
            } catch (e) {}
            showToast(detail);
            buttons.forEach((b) => (b.disabled = false));
        })
        .catch(() => {
            showToast("Could not submit rating. Please try again.");
            buttons.forEach((b) => (b.disabled = false));
        });
}

function addBundleToCart(bundleId) {
    fetch(`/store/api/bundle/${bundleId}/add-to-cart/`)
        .then((response) => response.json())
        .then((data) => {
            if (!data.products || data.products.length === 0) {
                showToast("No products found in this bundle.");
                return;
            }
            data.products.forEach((product) => {
                const variantId = String(product.default_variant_id);
                const existing = cart.find((item) => item.variantId === variantId);
                if (existing) {
                    existing.qty += 1;
                } else {
                    cart.push({
                        variantId,
                        productId: String(product.id),
                        name: product.name,
                        unitPrice: Number(product.display_price),
                        image: (product.variants && product.variants[0] && product.variants[0].image) || product.image || "",
                        weight: product.display_weight || "",
                        qty: 1,
                    });
                }
            });
            persistCart();
            showToast(`${data.bundle_name} added to cart!`);
            analyticsEvent("add_to_cart", {
                currency: "PKR",
                value: data.products.reduce((sum, product) => sum + Number(product.display_price || 0), 0),
                bundle_id: String(bundleId || ""),
                item_count: data.products.length,
            });
        })
        .catch(() => showToast("Error adding bundle to cart."));
}

function selectGramCard(btn) {
    const card = btn.closest(".product-card");
    card.querySelectorAll(".gram-btn").forEach((button) => button.classList.remove("active"));
    btn.classList.add("active");
    const cartBtn = card.querySelector(".btn-add-cart");
    const priceEl = card.querySelector("[data-card-price]");
    const weightEl = card.querySelector("[data-card-weight]");
    if (priceEl) priceEl.textContent = btn.dataset.price;
    if (weightEl) weightEl.textContent = btn.dataset.weight;
    if (cartBtn) {
        cartBtn.dataset.variantId = btn.dataset.variantId;
        cartBtn.dataset.price = btn.dataset.price;
        cartBtn.dataset.weight = btn.dataset.weight;
        cartBtn.dataset.productId = btn.dataset.pid;
    }
}

function selectedDetailOption() {
    return document.querySelector("#grammageOptions .option-btn.active");
}

function selectGrammage(btn) {
    document.querySelectorAll("#grammageOptions .option-btn").forEach((button) => button.classList.remove("active"));
    btn.classList.add("active");
    const price = document.getElementById("detailPrice");
    if (price) {
        price.textContent = btn.dataset.price || "0";
    }
    const addButton = document.getElementById("addToCartBtn");
    if (addButton) {
        const sellable = btn.dataset.sellable === "1";
        addButton.disabled = !sellable;
        addButton.textContent = sellable ? "Add to Cart" : "Out of Stock";
    }
}

function changeQty(delta) {
    const qtyInput = document.getElementById("qtyInput");
    if (!qtyInput) {
        return;
    }
    const next = Math.max(1, Number(qtyInput.textContent || 1) + Number(delta || 0));
    qtyInput.textContent = next;
}

function addToCartDetail() {
    const active = selectedDetailOption();
    const addButton = document.getElementById("addToCartBtn");
    if (!active || !addButton || addButton.disabled) {
        return;
    }
    const qty = Math.max(1, Number((document.getElementById("qtyInput") || {}).textContent || 1));
    for (let i = 0; i < qty; i += 1) {
        addToCart(
            active.dataset.variantId || "",
            addButton.dataset.productName || "Product",
            Number(active.dataset.price || 0),
            active.dataset.image || "",
            active.dataset.weight || "",
            addButton.dataset.productId || active.dataset.productId || "",
        );
    }
}

function addCardToCart(btn) {
    const card = btn.closest(".product-card");
    const nameEl = card ? card.querySelector(".product-name") : null;
    const imageEl = card ? card.querySelector(".card-img") : null;
    addToCart(
        btn.dataset.variantId,
        nameEl ? nameEl.textContent.trim() : "Product",
        Number(btn.dataset.price || 0),
        btn.dataset.image || (imageEl ? imageEl.src : ""),
        btn.dataset.weight || "",
        btn.dataset.productId || "",
    );
}

document.addEventListener("click", (event) => {
    const actionTarget = event.target.closest("[data-action]");
    if (!actionTarget) {
        return;
    }
    const action = actionTarget.dataset.action;
    if (action === "toggle-menu") {
        event.preventDefault();
        toggleMenu();
    } else if (action === "select-card-gram") {
        event.preventDefault();
        selectGramCard(actionTarget);
    } else if (action === "add-card-to-cart") {
        event.preventDefault();
        addCardToCart(actionTarget);
    } else if (action === "add-bundle-to-cart") {
        event.preventDefault();
        addBundleToCart(actionTarget.dataset.bundleId);
    } else if (action === "select-detail-gram") {
        event.preventDefault();
        selectGrammage(actionTarget);
    } else if (action === "change-detail-qty") {
        event.preventDefault();
        changeQty(Number(actionTarget.dataset.delta || 0));
    } else if (action === "add-detail-to-cart") {
        event.preventDefault();
        addToCartDetail();
    } else if (action === "switch-tab") {
        event.preventDefault();
        switchTab(actionTarget.dataset.tabGroup, actionTarget.dataset.tab);
    }
});

document.addEventListener("click", (event) => {
    const ratingButton = event.target.closest("[data-rating]");
    if (!ratingButton) {
        return;
    }
    event.preventDefault();
    rate(ratingButton.dataset.rating);
});

function switchTab(tabGroup, tabName) {
    document.querySelectorAll(`[data-tab-group="${tabGroup}"]`).forEach((el) => {
        el.classList.toggle("active", el.dataset.tab === tabName);
    });
}

document.addEventListener("DOMContentLoaded", () => {
    persistCart();
    renderCart();

    document.querySelectorAll(".nav-links a").forEach((link) => {
        link.addEventListener("click", () => {
            document.querySelector(".nav-links").classList.remove("active");
        });
    });

    document.querySelectorAll(".fade-up").forEach((el, index) => {
        el.style.animationDelay = `${index * 0.1}s`;
    });

    ensureAnalyticsConsentBanner();
});
