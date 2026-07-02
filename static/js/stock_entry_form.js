function normalizeText(text) {
    return String(text || "")
        .toLowerCase()
        .normalize("NFD")
        .replace(/[\u0300-\u036f]/g, "")
        .replace(",", ".");
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
    const selectedUnit = card.dataset.unit;
    const selectedPrice = card.dataset.price;

    document.getElementById("selected_product_id").value = selectedId;

    const selectedBox = document.getElementById("selected_product_box");
    selectedBox.style.display = "block";
    selectedBox.innerHTML = `
        Produto selecionado: ${selectedName}
        <br>
        <small>${selectedCategory} · ${selectedUnit} · Venda R$ ${selectedPrice}</small>
    `;

    document.querySelectorAll(".product-card").forEach(item => {
        item.classList.remove("selected");
    });

    card.classList.add("selected");
}

function validateSelectedProduct() {
    const selectedProductId = document.getElementById("selected_product_id").value;

    if (!selectedProductId) {
        alert("Selecione um produto antes de salvar a entrada.");
        return false;
    }

    return true;
}

function toggleMode() {
    const selected = document.querySelector('input[name="entry_mode"]:checked').value;

    const simpleFields = document.getElementById("simple-fields");
    const detailedFields = document.getElementById("detailed-fields");

    if (selected === "simple") {
        simpleFields.classList.remove("hidden");
        detailedFields.classList.add("hidden");
    } else {
        simpleFields.classList.add("hidden");
        detailedFields.classList.remove("hidden");
    }
}

document.getElementById("stock_entry_form").addEventListener("submit", event => {
    if (!validateSelectedProduct()) {
        event.preventDefault();
    }
});

document.getElementById("product_search").addEventListener("input", filterProducts);

document.querySelectorAll(".product-card").forEach(card => {
    card.addEventListener("click", () => selectProduct(card));
});

document.querySelectorAll('input[name="entry_mode"]').forEach(input => {
    input.addEventListener("change", toggleMode);
});

filterProducts();
