const unitsByDimension = {
    count: ["unit"],
    weight: ["mg", "g", "kg"],
    volume: ["mL", "L"],
};

const unitLabels = {
    unit: "un",
    mg: "mg",
    g: "g",
    kg: "kg",
    mL: "mL",
    L: "L",
};

const form = document.getElementById("stock_entry_form");
const productInput = document.getElementById("id_product");
const productPicker = document.getElementById("product_picker");
const productSearch = document.getElementById("product_search");
const selectedBox = document.getElementById("selected_product_box");
const entryFields = document.getElementById("entry_fields");
const quantityInput = document.getElementById("id_input_quantity");
const unitSelect = document.getElementById("id_input_unit");
const priceInput = document.getElementById("id_price");
const expirationInput = document.getElementById("id_expiration_date");

function normalizeText(text) {
    return String(text || "")
        .toLowerCase()
        .normalize("NFD")
        .replace(/[\u0300-\u036f]/g, "")
        .replace(",", ".");
}

function parseNumber(value) {
    const parsed = Number(String(value || "").trim().replace(",", "."));
    return Number.isFinite(parsed) ? parsed : null;
}

function selectedProductCard() {
    const selectedId = productInput.value;
    return Array.from(document.querySelectorAll(".product-card"))
        .find(card => card.dataset.id === selectedId) || null;
}

function filterProducts() {
    const query = normalizeText(productSearch.value);
    const cards = document.querySelectorAll(".product-card");
    let visibleCount = 0;

    cards.forEach(card => {
        const visible = query === "" || normalizeText(card.dataset.search).includes(query);
        card.style.display = visible ? "" : "none";
        if (visible) visibleCount += 1;
    });

    document.getElementById("no_results").style.display = visibleCount === 0 ? "block" : "none";
}

function updateAvailableUnits(dimension, preferredUnit = "", preserveCurrent = false) {
    const allowed = unitsByDimension[dimension] || [];
    const current = unitSelect.value;

    Array.from(unitSelect.options).forEach(option => {
        const available = option.value === "" || allowed.includes(option.value);
        option.hidden = !available;
        option.disabled = !available;
    });

    if (preserveCurrent && allowed.includes(current)) {
        unitSelect.value = current;
    } else if (allowed.includes(preferredUnit)) {
        unitSelect.value = preferredUnit;
    } else {
        unitSelect.value = allowed[0] || "";
    }
}

function updateSelectedProductSummary(card) {
    document.getElementById("selected_product_name").textContent = card.dataset.name;
    document.getElementById("selected_product_stock").textContent = card.dataset.currentStock;
    document.getElementById("selected_product_last_unit").textContent = card.dataset.lastUnit;

    const lastDateWrap = document.getElementById("selected_product_last_date_wrap");
    const lastDate = card.dataset.lastEntryDate || "";
    document.getElementById("selected_product_last_date").textContent = lastDate;
    lastDateWrap.hidden = lastDate === "";
}

function selectProduct(card, preserveUnit = false) {
    productInput.value = card.dataset.id;
    updateSelectedProductSummary(card);
    selectedBox.classList.add("is-visible");
    productPicker.classList.add("is-collapsed");
    entryFields.classList.add("is-ready");

    document.querySelectorAll(".product-card").forEach(item => {
        item.classList.toggle("selected", item === card);
    });

    updateAvailableUnits(
        card.dataset.dimension,
        card.dataset.preferredUnit,
        preserveUnit,
    );
    updatePricePresentation();
    updateConfirmation();
}

function changeProduct() {
    productInput.value = "";
    unitSelect.value = "";
    selectedBox.classList.remove("is-visible");
    productPicker.classList.remove("is-collapsed");
    entryFields.classList.remove("is-ready");
    document.querySelectorAll(".product-card").forEach(card => {
        card.classList.remove("selected");
    });
    productSearch.value = "";
    filterProducts();
    updatePricePresentation();
    updateConfirmation();
    productSearch.focus();
}

function selectedPriceMode() {
    return document.querySelector('input[name="price_mode"]:checked')?.value || "total";
}

function updatePricePresentation() {
    const mode = selectedPriceMode();
    const unit = unitSelect.value;
    const readableUnit = unitLabels[unit] || unit;
    document.getElementById("price_label").textContent = mode === "total"
        ? "Valor total"
        : `Preço por ${readableUnit || "medida"}`;
    document.getElementById("price_unit_suffix").textContent =
        mode === "per_unit" && readableUnit ? `por ${readableUnit}` : "";
    updateCalculationPreview();
    updateConfirmation();
}

function updateCalculationPreview() {
    const preview = document.getElementById("calculation_preview");
    const quantity = parseNumber(quantityInput.value);
    const price = parseNumber(priceInput.value);
    const unit = unitSelect.value;
    if (quantity === null || quantity <= 0 || price === null || price < 0 || !unit) {
        preview.textContent = "";
        preview.classList.remove("is-visible");
        return;
    }

    const { formatCurrency } = window.BarFormatting;
    if (selectedPriceMode() === "per_unit") {
        preview.textContent = `Total estimado: ${formatCurrency(quantity * price)}`;
    } else {
        preview.textContent = `${formatCurrency(price / quantity)}/${unitLabels[unit]}`;
    }
    preview.classList.add("is-visible");
}

function formatDate(dateValue) {
    const parts = String(dateValue || "").split("-");
    if (parts.length !== 3) return "";
    return `${parts[2]}/${parts[1]}/${parts[0]}`;
}

function updateConfirmation() {
    const card = selectedProductCard();
    const rawQuantity = quantityInput.value.trim();
    const quantity = parseNumber(rawQuantity);
    const unit = unitSelect.value;
    const price = parseNumber(priceInput.value);
    const quantityLine = document.getElementById("confirmation_quantity");
    const priceLine = document.getElementById("confirmation_price");
    const expirationLine = document.getElementById("confirmation_expiration");

    if (card && quantity !== null && quantity > 0 && unit) {
        quantityLine.textContent = `${rawQuantity} ${unitLabels[unit]} de ${card.dataset.name}`;
    } else {
        quantityLine.textContent = "Escolha o produto e informe a quantidade.";
    }

    if (price !== null && price >= 0) {
        const { formatCurrency } = window.BarFormatting;
        const total = selectedPriceMode() === "per_unit" && quantity !== null
            ? quantity * price
            : price;
        priceLine.textContent = `Valor total: ${formatCurrency(total)}`;
    } else {
        priceLine.textContent = "";
    }

    const expiration = formatDate(expirationInput.value);
    expirationLine.textContent = expiration ? `Validade: ${expiration}` : "Sem validade informada";
}

function initializeSelection() {
    const card = selectedProductCard();
    if (card) {
        selectProduct(card, form.dataset.formBound === "true" || unitSelect.value !== "");
    } else {
        updatePricePresentation();
        updateConfirmation();
    }
}

form.addEventListener("submit", event => {
    if (!productInput.value) {
        event.preventDefault();
        productPicker.classList.remove("is-collapsed");
        productSearch.focus();
    }
});

productSearch.addEventListener("input", filterProducts);
quantityInput.addEventListener("input", () => {
    updateCalculationPreview();
    updateConfirmation();
});
priceInput.addEventListener("input", () => {
    updateCalculationPreview();
    updateConfirmation();
});
unitSelect.addEventListener("change", updatePricePresentation);
expirationInput.addEventListener("input", updateConfirmation);
document.getElementById("change_product_button").addEventListener("click", changeProduct);
document.querySelectorAll('input[name="price_mode"]').forEach(input => {
    input.addEventListener("change", updatePricePresentation);
});
document.querySelectorAll(".product-card").forEach(card => {
    card.addEventListener("click", () => selectProduct(card));
});

filterProducts();
initializeSelection();
