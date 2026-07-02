let selectedStock = null;
let selectedUnit = "";

function normalizeText(text) {
    return String(text || "")
        .toLowerCase()
        .normalize("NFD")
        .replace(/[\u0300-\u036f]/g, "")
        .replace(",", ".");
}

function parseNumber(value) {
    const normalized = String(value || "").replace(",", ".");
    const number = Number(normalized);

    if (Number.isNaN(number)) {
        return null;
    }

    return number;
}

function filterProducts() {
    const query = normalizeText(document.getElementById("product_search").value);
    const cards = document.querySelectorAll(".product-card");
    const noResults = document.getElementById("no_results");

    let visibleCount = 0;

    cards.forEach(card => {
        const searchable = normalizeText(card.dataset.search);
        const shouldShow = query === "" || searchable.includes(query);

        if (shouldShow) {
            card.style.display = "block";
            visibleCount += 1;
        } else {
            card.style.display = "none";
        }
    });

    noResults.style.display = visibleCount === 0 ? "block" : "none";
}

function selectProduct(card) {
    const selectedId = card.dataset.id;
    const selectedName = card.dataset.name;
    const selectedCategory = card.dataset.category;

    selectedStock = parseNumber(card.dataset.stock);
    selectedUnit = card.dataset.unit;

    document.getElementById("selected_product_id").value = selectedId;

    const selectedBox = document.getElementById("selected_product_box");
    selectedBox.style.display = "block";
    selectedBox.innerHTML = `
        Produto selecionado: ${selectedName}
        <br>
        <small>${selectedCategory} · Estoque esperado: ${selectedStock.toFixed(2)} ${selectedUnit}</small>
    `;

    document.querySelectorAll(".product-card").forEach(item => {
        item.classList.remove("selected");
    });

    card.classList.add("selected");

    calculateDifference();
}

function calculateDifference() {
    const realQuantity = parseNumber(document.getElementById("real_quantity").value);
    const differenceBox = document.getElementById("difference_box");

    if (selectedStock === null || realQuantity === null) {
        differenceBox.style.display = "none";
        return;
    }

    const difference = realQuantity - selectedStock;

    differenceBox.style.display = "block";

    if (difference > 0) {
        differenceBox.innerHTML = `
            Diferença:
            <span class="difference-positive">+${difference.toFixed(2)} ${selectedUnit}</span>
            <br>
            Será criado um ajuste positivo.
        `;
    } else if (difference < 0) {
        differenceBox.innerHTML = `
            Diferença:
            <span class="difference-negative">${difference.toFixed(2)} ${selectedUnit}</span>
            <br>
            Será criado um ajuste negativo.
        `;
    } else {
        differenceBox.innerHTML = `
            Diferença:
            <span class="difference-zero">0.00 ${selectedUnit}</span>
            <br>
            A conferência será registrada sem alterar o estoque.
        `;
    }
}

function validateForm() {
    const selectedProductId = document.getElementById("selected_product_id").value;
    const realQuantity = parseNumber(document.getElementById("real_quantity").value);

    if (!selectedProductId) {
        alert("Selecione um produto antes de aplicar a conferência.");
        return false;
    }

    if (realQuantity === null || realQuantity < 0) {
        alert("Informe uma contagem real válida.");
        return false;
    }

    return confirm("Confirmar conferência de estoque?");
}

document.getElementById("stock_count_form").addEventListener("submit", event => {
    if (!validateForm()) {
        event.preventDefault();
    }
});

document.getElementById("product_search").addEventListener("input", filterProducts);
document.getElementById("real_quantity").addEventListener("input", calculateDifference);

document.querySelectorAll(".product-card").forEach(card => {
    card.addEventListener("click", () => selectProduct(card));
});

filterProducts();
