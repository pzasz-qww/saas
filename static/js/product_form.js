document.addEventListener("DOMContentLoaded", () => {
    const rows = document.getElementById("component-rows");
    const addButton = document.getElementById("add-component");
    const template = document.getElementById("empty-component-form");
    const totalForms = document.getElementById("id_components-TOTAL_FORMS");

    function bindRemoveButton(row) {
        const removeButton = row.querySelector(".remove-component");
        const deleteInput = row.querySelector('input[name$="-DELETE"]');
        if (!removeButton) {
            return;
        }

        removeButton.addEventListener("click", () => {
            if (deleteInput) {
                deleteInput.checked = true;
            }
            row.hidden = true;
            row.querySelectorAll("select, input").forEach((field) => {
                if (field !== deleteInput) {
                    field.removeAttribute("required");
                }
            });
        });
    }

    if (rows) {
        rows.querySelectorAll(".component-row").forEach(bindRemoveButton);
    }

    if (rows && addButton && template && totalForms) {
        addButton.addEventListener("click", () => {
            const index = Number.parseInt(totalForms.value, 10);
            const html = template.innerHTML.replaceAll("__prefix__", String(index));
            rows.insertAdjacentHTML("beforeend", html);
            const newRow = rows.lastElementChild;
            bindRemoveButton(newRow);
            totalForms.value = String(index + 1);
        });
    }

    const saleForm = document.getElementById("sale_form");
    const inventoryRole = document.getElementById("inventory_role");
    const preparationField = document.querySelector("[data-preparation-field]");

    function updateOptionalFields() {
        document.querySelectorAll("[data-sale-form-field]").forEach((field) => {
            const shouldShow = field.dataset.saleFormField === saleForm?.value;
            field.hidden = !shouldShow;
            if (!shouldShow) {
                const input = field.querySelector("input");
                if (input) {
                    input.value = "";
                }
            }
        });

        if (preparationField) {
            const shouldShow = inventoryRole?.value === "prepared";
            preparationField.hidden = !shouldShow;
            if (!shouldShow) {
                const select = preparationField.querySelector("select");
                if (select) {
                    select.value = "";
                }
            }
        }
    }

    saleForm?.addEventListener("change", updateOptionalFields);
    inventoryRole?.addEventListener("change", updateOptionalFields);
    updateOptionalFields();
});
