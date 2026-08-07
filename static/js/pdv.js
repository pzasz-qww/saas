let cart = [];

const cartElement = document.getElementById("cart");
const cartToggleButton = document.getElementById("cart-toggle-button");
const cartSummaryCount = document.getElementById("cart-summary-count");
const cartSummaryTotal = document.getElementById("cart-summary-total");
const clearCartButton = document.getElementById("clear-cart-button");
const cartForm = document.getElementById("cart-form");
const cartSubmitButton = document.getElementById("cart-submit-button");
let cartSubmissionInProgress = false;
const cartDataInput = document.getElementById("cart_data");
const productButtons = document.querySelectorAll(".product-button");
const initialCartElement = document.getElementById("pdv-initial-cart");

function loadInitialCart() {
    if (!initialCartElement) {
        return [];
    }

    try {
        const parsedCart = JSON.parse(initialCartElement.textContent);

        if (!Array.isArray(parsedCart)) {
            return [];
        }

        return parsedCart.flatMap(item => {
            const id = String(item.id || "");
            const name = typeof item.name === "string" ? item.name : "";
            const price = Number(item.price);
            const quantity = Number(item.quantity);

            if (
                !id
                || !name
                || !Number.isFinite(price)
                || price < 0
                || !Number.isInteger(quantity)
                || quantity <= 0
            ) {
                return [];
            }

            return [{ id, name, price, quantity }];
        });
    } catch (error) {
        return [];
    }
}

function formatMoney(value) {
    return value.toLocaleString("pt-BR", {
        style: "currency",
        currency: "BRL"
    });
}

function addToCart(id, name, price) {
    const numericPrice = Number(String(price).replace(",", "."));

    const existing = cart.find(item => item.id === id);

    if (existing) {
        existing.quantity += 1;
    } else {
        cart.push({
            id: id,
            name: name,
            price: numericPrice,
            quantity: 1
        });
    }

    renderCart();
}

function increaseItem(id) {
    const item = cart.find(item => item.id === id);

    if (item) {
        item.quantity += 1;
    }

    renderCart();
}

function decreaseItem(id) {
    const item = cart.find(item => item.id === id);

    if (!item) {
        return;
    }

    item.quantity -= 1;

    if (item.quantity <= 0) {
        cart = cart.filter(item => item.id !== id);
    }

    renderCart();
}

function removeItem(id) {
    cart = cart.filter(item => item.id !== id);
    renderCart();
}

function clearCart() {
    cart = [];
    renderCart();
}

function updateCartSummary(total) {
    const itemCount = cart.reduce((count, item) => count + item.quantity, 0);
    const itemLabel = itemCount === 1 ? "item" : "itens";

    cartSummaryCount.textContent = `${itemCount} ${itemLabel}`;
    cartSummaryTotal.textContent = formatMoney(total);
    clearCartButton.disabled = itemCount === 0;
}

function createCartActionButton(text, className, clickHandler) {
    const button = document.createElement("button");
    button.className = className;
    button.type = "button";
    button.textContent = text;
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
        return;
    }

    let total = 0;

    cart.forEach(item => {
        const itemTotal = item.price * item.quantity;
        total += itemTotal;

        const div = document.createElement("div");
        div.className = "cart-item";

        const itemDetails = document.createElement("div");

        const itemName = document.createElement("div");
        itemName.className = "cart-item-name";
        itemName.textContent = `${item.quantity}x ${item.name}`;

        const itemMeta = document.createElement("div");
        itemMeta.className = "cart-item-meta";
        itemMeta.textContent = `${formatMoney(item.price)} cada · ${formatMoney(itemTotal)}`;

        itemDetails.append(itemName, itemMeta);

        const actions = document.createElement("div");
        actions.className = "cart-actions";
        actions.append(
            createCartActionButton("-", "small-button", () => decreaseItem(item.id)),
            createCartActionButton("+", "small-button", () => increaseItem(item.id)),
            createCartActionButton("x", "small-button remove-button", () => removeItem(item.id))
        );

        div.append(itemDetails, actions);

        container.appendChild(div);
    });

    totalElement.textContent = formatMoney(total);
    updateCartSummary(total);
}

function prepareCartData() {
    cartDataInput.value = JSON.stringify(cart);
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
        addToCart(
            button.dataset.productId,
            button.dataset.productName,
            button.dataset.productPrice
        );
    });
});

cartToggleButton.addEventListener("click", toggleMobileCart);
clearCartButton.addEventListener("click", clearCart);
cartForm.addEventListener("submit", (event) => {
    prepareCartData();

    if (cartSubmissionInProgress) {
        event.preventDefault();
        return;
    }

    cartSubmissionInProgress = true;
    cartSubmitButton.disabled = true;
    cartSubmitButton.textContent = "Enviando...";
});

cart = loadInitialCart();
renderCart();
