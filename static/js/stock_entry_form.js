const unitsByDimension = {
    count: ["unit"],
    weight: ["mg", "g", "kg"],
    volume: ["mL", "L"],
};

const unitLabels = {
    unit: "unidade",
    mg: "mg",
    g: "g",
    kg: "kg",
    mL: "mL",
    L: "L",
};

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
    const selectedId = document.getElementById("id_product").value;
    return Array.from(document.querySelectorAll(".product-card"))
        .find(card => card.dataset.id === selectedId) || null;
}

function filterProducts() {
    const query = normalizeText(document.getElementById("product_search").value);
    const cards = document.querySelectorAll(".product-card");
    let visibleCount = 0;

    cards.forEach(card => {
        const visible = query === "" || normalizeText(card.dataset.search).includes(query);
        card.style.display = visible ? "block" : "none";
        if (visible) visibleCount += 1;
    });

    document.getElementById("no_results").style.display = visibleCount === 0 ? "block" : "none";
}

function updateAvailableUnits(dimension, preserveCurrent = false) {
    const unitSelect = document.getElementById("id_input_unit");
    const allowed = unitsByDimension[dimension] || [];
    const current = unitSelect.value;

    Array.from(unitSelect.options).forEach(option => {
        const available = option.value === "" || allowed.includes(option.value);
        option.hidden = !available;
        option.disabled = !available;
    });

    if (!preserveCurrent || !allowed.includes(current)) {
        unitSelect.value = allowed.length === 1 ? allowed[0] : "";
    }
}

function selectProduct(card) {
    document.getElementById("id_product").value = card.dataset.id;
    const selectedBox = document.getElementById("selected_product_box");
    const category = card.dataset.category || "Sem categoria";
    const details = document.createElement("small");
    details.textContent = `${category} - ${card.dataset.dimensionLabel}`;
    selectedBox.replaceChildren(
        document.createTextNode(`Produto selecionado: ${card.dataset.name}`),
        document.createElement("br"),
        details,
    );
    selectedBox.classList.add("is-visible");

    document.querySelectorAll(".product-card").forEach(item => {
        item.classList.toggle("selected", item === card);
    });

    updateAvailableUnits(card.dataset.dimension);
    updatePricePresentation();
}

function selectedPriceMode() {
    return document.querySelector('input[name="price_mode"]:checked')?.value || "total";
}

function updatePricePresentation() {
    const mode = selectedPriceMode();
    const unit = document.getElementById("id_input_unit").value;
    document.getElementById("price_label").textContent = mode === "total"
        ? "Pre\u00e7o total"
        : "Pre\u00e7o por medida";
    document.getElementById("price_unit_suffix").textContent =
        mode === "per_unit" && unit ? `por ${unitLabels[unit]}` : "";
    updateCalculationPreview();
}

function updateCalculationPreview() {
    const preview = document.getElementById("calculation_preview");
    const quantity = parseNumber(document.getElementById("id_input_quantity").value);
    const price = parseNumber(document.getElementById("id_price").value);
    const unit = document.getElementById("id_input_unit").value;
    if (quantity === null || quantity <= 0 || price === null || price < 0 || !unit) {
        preview.textContent = "";
        preview.classList.remove("is-visible");
        return;
    }

    const formatter = new Intl.NumberFormat("pt-BR", {
        style: "currency",
        currency: "BRL",
    });
    if (selectedPriceMode() === "per_unit") {
        preview.textContent = `Total estimado: ${formatter.format(quantity * price)}`;
    } else {
        preview.textContent = `Pre\u00e7o equivalente: ${formatter.format(price / quantity)} por ${unitLabels[unit]}`;
    }
    preview.classList.add("is-visible");
}

function initializeSelection() {
    const card = selectedProductCard();
    if (card) {
        updateAvailableUnits(card.dataset.dimension, true);
    }
    updatePricePresentation();
}

document.getElementById("stock_entry_form").addEventListener("submit", event => {
    if (!document.getElementById("id_product").value) {
        event.preventDefault();
        document.getElementById("product_search").focus();
    }
});

document.getElementById("product_search").addEventListener("input", filterProducts);
document.getElementById("id_input_quantity").addEventListener("input", updateCalculationPreview);
document.getElementById("id_price").addEventListener("input", updateCalculationPreview);
document.getElementById("id_input_unit").addEventListener("change", updatePricePresentation);
document.querySelectorAll('input[name="price_mode"]').forEach(input => {
    input.addEventListener("change", updatePricePresentation);
});
document.querySelectorAll(".product-card").forEach(card => {
    card.addEventListener("click", () => selectProduct(card));
});

filterProducts();
initializeSelection();
