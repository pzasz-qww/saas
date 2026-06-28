let cart = [];

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

function renderCart() {
    const container = document.getElementById("cart-items");
    const totalElement = document.getElementById("cart-total");

    container.innerHTML = "";

    if (cart.length === 0) {
        container.innerHTML = '<div class="empty-cart">Nenhum item no carrinho.</div>';
        totalElement.innerText = "R$ 0,00";
        return;
    }

    let total = 0;

    cart.forEach(item => {
        const itemTotal = item.price * item.quantity;
        total += itemTotal;

        const div = document.createElement("div");
        div.className = "cart-item";

        div.innerHTML = `
            <div>
                <div class="cart-item-name">${item.quantity}x ${item.name}</div>
                <div class="cart-item-meta">${formatMoney(item.price)} cada · ${formatMoney(itemTotal)}</div>
            </div>

            <div class="cart-actions">
                <button class="small-button" type="button" onclick="decreaseItem('${item.id}')">-</button>
                <button class="small-button" type="button" onclick="increaseItem('${item.id}')">+</button>
                <button class="small-button remove-button" type="button" onclick="removeItem('${item.id}')">x</button>
            </div>
        `;

        container.appendChild(div);
    });

    totalElement.innerText = formatMoney(total);
}

function prepareCartData() {
    document.getElementById("cart_data").value = JSON.stringify(cart);
}

function toggleMobileCart() {

    document
        .getElementById("cart")
        .classList
        .toggle("open");

}