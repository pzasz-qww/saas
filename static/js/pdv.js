let cart = [];
let selectedCategory = "all";
let cartSubmissionInProgress = false;

const cartElement = document.getElementById("cart");
const cartToggleButton = document.getElementById("cart-toggle-button");
const cartSummaryCount = document.getElementById("cart-summary-count");
const cartSummaryTotal = document.getElementById("cart-summary-total");
const clearCartButton = document.getElementById("clear-cart-button");
const cartForm = document.getElementById("cart-form");
const cartSubmitButton = document.getElementById("cart-submit-button");
const cartDataInput = document.getElementById("cart_data");
const initialCartElement = document.getElementById("pdv-initial-cart");
const productSearch = document.getElementById("product_search");
const productCards = Array.from(document.querySelectorAll("[data-product-card]"));
const productButtons = Array.from(document.querySelectorAll(".product-button"));
const categoryButtons = Array.from(document.querySelectorAll(".category-filter"));
const cartNotice = document.getElementById("pdv_cart_notice");

const productCatalog = new Map(productButtons.map(button => [
    button.dataset.productId,
    {
        id: button.dataset.productId,
        name: button.dataset.productName,
        price: Number(String(button.dataset.productPrice).replace(",", ".")),
        available: Number(button.dataset.productAvailable),
        button,
    },
]));

function normalizeText(text) {
    return String(text || "")
        .toLocaleLowerCase("pt-BR")
        .normalize("NFD")
        .replace(/[\u0300-\u036f]/g, "")
        .trim();
}

function formatMoney(value) {
    return value.toLocaleString("pt-BR", {
        style: "currency",
        currency: "BRL",
    });
}

function showCartNotice(message) {
    cartNotice.textContent = message;
    cartNotice.classList.toggle("is-visible", Boolean(message));
}

function loadInitialCart() {
    if (!initialCartElement) return [];

    try {
        const parsedCart = JSON.parse(initialCartElement.textContent);
        if (!Array.isArray(parsedCart)) return [];

        return parsedCart.flatMap(item => {
            const product = productCatalog.get(String(item.id || ""));
            const quantity = Number(item.quantity);
            if (
                !product
                || !Number.isFinite(product.price)
                || product.price < 0
                || !Number.isInteger(product.available)
                || product.available <= 0
                || !Number.isInteger(quantity)
                || quantity <= 0
            ) {
                return [];
            }
            return [{
                id: product.id,
                name: product.name,
                price: product.price,
                quantity: Math.min(quantity, product.available),
                available: product.available,
            }];
        });
    } catch (error) {
        return [];
    }
}

function addToCart(product) {
    const existing = cart.find(item => item.id === product.id);
    if (existing && existing.quantity >= product.available) {
        showCartNotice(`Limite atual de ${product.name}: ${product.available}.`);
        return;
    }

    if (existing) {
        existing.quantity += 1;
    } else if (product.available > 0) {
        cart.push({
            id: product.id,
            name: product.name,
            price: product.price,
            quantity: 1,
            available: product.available,
        });
    }
    showCartNotice("");
    renderCart();
}

function increaseItem(id) {
    const item = cart.find(cartItem => cartItem.id === id);
    if (!item) return;
    if (item.quantity >= item.available) {
        showCartNotice(`Limite atual de ${item.name}: ${item.available}.`);
        return;
    }
    item.quantity += 1;
    showCartNotice("");
    renderCart();
}

function decreaseItem(id) {
    const item = cart.find(cartItem => cartItem.id === id);
    if (!item) return;
    item.quantity -= 1;
    if (item.quantity <= 0) {
        cart = cart.filter(cartItem => cartItem.id !== id);
    }
    showCartNotice("");
    renderCart();
}

function removeItem(id) {
    cart = cart.filter(item => item.id !== id);
    showCartNotice("");
    renderCart();
}

function clearCart() {
    cart = [];
    showCartNotice("");
    renderCart();
}

function updateCartSummary(total) {
    const itemCount = cart.reduce((count, item) => count + item.quantity, 0);
    const itemLabel = itemCount === 1 ? "item" : "itens";
    cartSummaryCount.textContent = `${itemCount} ${itemLabel}`;
    cartSummaryTotal.textContent = formatMoney(total);
    clearCartButton.disabled = itemCount === 0;
    cartSubmitButton.disabled = itemCount === 0 || cartSubmissionInProgress;
}

function updateProductButtons() {
    productCatalog.forEach(product => {
        const item = cart.find(cartItem => cartItem.id === product.id);
        const atLimit = item && item.quantity >= product.available;
        product.button.disabled = product.available <= 0 || atLimit;
        product.button.setAttribute(
            "aria-disabled",
            String(product.available <= 0 || atLimit),
        );
        if (product.available <= 0) {
            product.button.textContent = "Esgotado";
        } else if (atLimit) {
            product.button.textContent = "Limite no carrinho";
        } else {
            product.button.textContent = "+ Adicionar";
        }
    });
}

function createCartActionButton(text, className, clickHandler, options = {}) {
    const button = document.createElement("button");
    button.className = className;
    button.type = "button";
    button.textContent = text;
    button.disabled = Boolean(options.disabled);
    if (options.label) button.setAttribute("aria-label", options.label);
    button.addEventListener("click", clickHandler);
    return button;
}

function renderCart() {
    const container = document.getElementById("cart-items");
    const totalElement = document.getElementById("cart-total");
    container.replaceChildren();

    if (cart.length === 0) {
        const emptyCart = document.createElement("div");
        emptyCart.className = "empty-cart";
        emptyCart.textContent = "Nenhum item no carrinho.";
        container.appendChild(emptyCart);
        totalElement.textContent = "R$ 0,00";
        updateCartSummary(0);
        updateProductButtons();
        return;
    }

    let total = 0;
    cart.forEach(item => {
        const itemTotal = item.price * item.quantity;
        total += itemTotal;

        const row = document.createElement("div");
        row.className = "cart-item";

        const itemDetails = document.createElement("div");
        itemDetails.className = "cart-item-details";
        const itemName = document.createElement("div");
        itemName.className = "cart-item-name";
        itemName.textContent = item.name;
        const itemMeta = document.createElement("div");
        itemMeta.className = "cart-item-meta";
        itemMeta.textContent = `${formatMoney(item.price)} cada · Subtotal ${formatMoney(itemTotal)}`;
        itemDetails.append(itemName, itemMeta);

        const actions = document.createElement("div");
        actions.className = "cart-actions";
        const quantity = document.createElement("span");
        quantity.className = "cart-item-quantity";
        quantity.textContent = String(item.quantity);
        quantity.setAttribute("aria-label", `Quantidade: ${item.quantity}`);
        actions.append(
            createCartActionButton(
                "−",
                "small-button",
                () => decreaseItem(item.id),
                { label: `Diminuir ${item.name}` },
            ),
            quantity,
            createCartActionButton(
                "+",
                "small-button",
                () => increaseItem(item.id),
                {
                    label: `Aumentar ${item.name}`,
                    disabled: item.quantity >= item.available,
                },
            ),
            createCartActionButton(
                "Remover",
                "remove-button",
                () => removeItem(item.id),
                { label: `Remover ${item.name}` },
            ),
        );
        row.append(itemDetails, actions);
        container.appendChild(row);
    });

    totalElement.textContent = formatMoney(total);
    updateCartSummary(total);
    updateProductButtons();
}

function applyProductFilters() {
    const query = normalizeText(productSearch.value);
    const normalizedCategory = normalizeText(selectedCategory);
    let visibleCount = 0;

    productCards.forEach(card => {
        const matchesSearch = !query || normalizeText(card.dataset.search).includes(query);
        const matchesCategory = selectedCategory === "all"
            || normalizeText(card.dataset.productCategory) === normalizedCategory;
        const visible = matchesSearch && matchesCategory;
        card.hidden = !visible;
        if (visible) visibleCount += 1;
    });

    document.querySelectorAll("[data-category-section]").forEach(section => {
        section.hidden = !Array.from(section.querySelectorAll("[data-product-card]"))
            .some(card => !card.hidden);
    });

    const noResults = document.getElementById("pdv_no_results");
    const noResultsText = document.getElementById("pdv_no_results_text");
    noResults.hidden = visibleCount !== 0;
    if (visibleCount === 0) {
        if (query && selectedCategory !== "all") {
            noResultsText.textContent = `Nenhum produto encontrado para "${productSearch.value.trim()}" nesta categoria.`;
        } else if (query) {
            noResultsText.textContent = `Nenhum produto encontrado para "${productSearch.value.trim()}".`;
        } else {
            noResultsText.textContent = "Nenhum produto encontrado nesta categoria.";
        }
    }
    document.getElementById("pdv_filter_status").textContent =
        `${visibleCount} ${visibleCount === 1 ? "produto encontrado" : "produtos encontrados"}.`;
}

function selectCategory(button) {
    selectedCategory = button.dataset.categoryFilter;
    categoryButtons.forEach(categoryButton => {
        const active = categoryButton === button;
        categoryButton.classList.toggle("is-active", active);
        categoryButton.setAttribute("aria-pressed", String(active));
    });
    applyProductFilters();
}

function clearProductFilters() {
    productSearch.value = "";
    const allButton = categoryButtons.find(button => button.dataset.categoryFilter === "all");
    if (allButton) selectCategory(allButton);
    productSearch.focus();
}

function prepareCartData() {
    cartDataInput.value = JSON.stringify(cart.map(item => ({
        id: item.id,
        quantity: item.quantity,
    })));
}

function toggleMobileCart() {
    const shouldExpand = !cartElement.classList.contains("is-expanded");
    cartElement.classList.toggle("is-expanded", shouldExpand);
    document.body.classList.toggle("mobile-cart-expanded", shouldExpand);
    cartToggleButton.setAttribute("aria-expanded", String(shouldExpand));
    cartToggleButton.textContent = shouldExpand ? "Recolher" : "Ver carrinho";
}

productButtons.forEach(button => {
    button.addEventListener("click", () => {
        const product = productCatalog.get(button.dataset.productId);
        if (product) addToCart(product);
    });
});
categoryButtons.forEach(button => {
    button.addEventListener("click", () => selectCategory(button));
});
productSearch.addEventListener("input", applyProductFilters);
document.getElementById("clear_product_filters").addEventListener("click", clearProductFilters);
cartToggleButton.addEventListener("click", toggleMobileCart);
clearCartButton.addEventListener("click", clearCart);
cartForm.addEventListener("submit", event => {
    if (cart.length === 0 || cartSubmissionInProgress) {
        event.preventDefault();
        return;
    }
    prepareCartData();
    cartSubmissionInProgress = true;
    cartSubmitButton.disabled = true;
    cartSubmitButton.textContent = "Enviando...";
});

cart = loadInitialCart();
applyProductFilters();
renderCart();
