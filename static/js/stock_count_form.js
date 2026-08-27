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

function formatQuantity(value) {
    return value.toLocaleString("pt-BR", {
        minimumFractionDigits: 0,
        maximumFractionDigits: 6,
    });
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
    const selectedCategory = card.dataset.category || "Sem categoria";

    selectedStock = parseNumber(card.dataset.stock);
    selectedUnit = card.dataset.unit;

    document.getElementById("selected_product_id").value = selectedId;

    const selectedBox = document.getElementById("selected_product_box");
    selectedBox.style.display = "block";
    const details = document.createElement("small");
    details.textContent = `${selectedCategory} · Estoque esperado: ${formatQuantity(selectedStock)} ${selectedUnit}`;
    selectedBox.replaceChildren(
        document.createTextNode(`Produto selecionado: ${selectedName}`),
        document.createElement("br"),
        details,
    );

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

    const differenceValue = document.createElement("span");
    let explanation = "";

    if (difference > 0) {
        differenceValue.className = "difference-positive";
        differenceValue.textContent = `+${formatQuantity(difference)} ${selectedUnit}`;
        explanation = "Será criado um ajuste positivo.";
    } else if (difference < 0) {
        differenceValue.className = "difference-negative";
        differenceValue.textContent = `${formatQuantity(difference)} ${selectedUnit}`;
        explanation = "Será criado um ajuste negativo.";
    } else {
        differenceValue.className = "difference-zero";
        differenceValue.textContent = `0 ${selectedUnit}`;
        explanation = "A conferência será registrada sem alterar o estoque.";
    }

    differenceBox.replaceChildren(
        document.createTextNode("Diferença: "),
        differenceValue,
        document.createElement("br"),
        document.createTextNode(explanation),
    );
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
