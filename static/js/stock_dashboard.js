let currentCategory = "all";
let currentStatus = "all";

function normalizeText(text) {
    return String(text || "")
        .toLowerCase()
        .normalize("NFD")
        .replace(/[\u0300-\u036f]/g, "")
        .replace(",", ".");
}

function buildCategoryButtons() {
    const rows = document.querySelectorAll(".stock-row");
    const container = document.getElementById("category_buttons");

    const categories = new Set();

    rows.forEach(row => {
        const category = row.dataset.category || "Sem categoria";
        categories.add(category);
    });

    const sortedCategories = Array.from(categories).sort((a, b) => {
        return a.localeCompare(b, "pt-BR");
    });

    sortedCategories.forEach(category => {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "filter-button";
        button.innerText = category;

        button.onclick = function () {
            setCategoryFilter(category, button);
        };

        container.appendChild(button);
    });
}

function setCategoryFilter(category, clickedButton) {
    currentCategory = category;

    const buttons = document.querySelectorAll("#category_buttons .filter-button");

    buttons.forEach(button => {
        button.classList.remove("active");
    });

    clickedButton.classList.add("active");

    applyFilters();
}

function setStatusFilter(status, clickedButton) {
    currentStatus = status;

    const buttons = clickedButton.parentElement.querySelectorAll(".filter-button");

    buttons.forEach(button => {
        button.classList.remove("active");
    });

    clickedButton.classList.add("active");

    applyFilters();
}

function applyFilters() {
    const query = normalizeText(document.getElementById("stock_search").value);
    const rows = document.querySelectorAll(".stock-row");
    const noResults = document.getElementById("no_results");
    const counter = document.getElementById("results_counter");

    let visibleCount = 0;
    let totalCount = rows.length;

    rows.forEach(row => {
        const searchable = normalizeText(row.dataset.search);
        const category = row.dataset.category || "Sem categoria";
        const status = row.dataset.status;

        const matchesSearch = query === "" || searchable.includes(query);
        const matchesCategory = currentCategory === "all" || category === currentCategory;

        let matchesStatus = false;

        if (currentStatus === "all") {
            matchesStatus = true;
        } else if (currentStatus === "critical") {
            matchesStatus = status === "low" || status === "empty";
        } else {
            matchesStatus = status === currentStatus;
        }

        const shouldShow = matchesSearch && matchesCategory && matchesStatus;

        if (shouldShow) {
            row.style.display = "";
            visibleCount += 1;
        } else {
            row.style.display = "none";
        }
    });

    noResults.style.display = visibleCount === 0 ? "block" : "none";

    counter.innerText = `${visibleCount} de ${totalCount} produtos exibidos`;
}

buildCategoryButtons();
applyFilters();
