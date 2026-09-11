document.addEventListener("DOMContentLoaded", () => {
    const rows = document.getElementById("component-rows");
    const addButton = document.getElementById("add-component");
    const template = document.getElementById("empty-component-form");
    const totalForms = document.getElementById("id_components-TOTAL_FORMS");
    const removeDialog = document.getElementById("remove-component-dialog");
    const removeQuestion = document.getElementById("remove-component-question");
    const cancelRemoval = document.getElementById("cancel-component-removal");
    const confirmRemoval = document.getElementById("confirm-component-removal");
    let pendingRemovalRow = null;

    function removeRow(row) {
        const deleteInput = row.querySelector('input[name$="-DELETE"]');
        if (deleteInput) {
            deleteInput.checked = true;
        }
        row.hidden = true;
        row.querySelectorAll("select, input").forEach((field) => {
            if (field !== deleteInput) {
                field.removeAttribute("required");
            }
        });
    }

    function bindRemoveButton(row) {
        const removeButton = row.querySelector(".remove-component");
        if (!removeButton) {
            return;
        }

        removeButton.addEventListener("click", () => {
            const componentId = row.querySelector('input[name$="-component_id"]');
            if (!componentId?.value) {
                removeRow(row);
                return;
            }

            const ingredient = row.querySelector('select[name$="-ingredient"]');
            const ingredientName = ingredient?.selectedOptions[0]?.textContent?.trim()
                || "este ingrediente";
            pendingRemovalRow = row;
            if (removeQuestion) {
                removeQuestion.textContent = `Remover “${ingredientName}” desta receita?`;
            }
            if (removeDialog?.showModal) {
                removeDialog.showModal();
            } else if (window.confirm(
                `Remover “${ingredientName}” desta receita? O histórico existente será preservado.`
            )) {
                removeRow(row);
                pendingRemovalRow = null;
            }
        });
    }

    cancelRemoval?.addEventListener("click", () => {
        pendingRemovalRow = null;
        removeDialog?.close();
    });

    confirmRemoval?.addEventListener("click", () => {
        if (pendingRemovalRow) {
            removeRow(pendingRemovalRow);
        }
        pendingRemovalRow = null;
        removeDialog?.close();
    });

    removeDialog?.addEventListener("close", () => {
        pendingRemovalRow = null;
    });

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
    const componentsSection = document.querySelector("[data-components-section]");

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
            if (componentsSection) {
                const hasPersistedComponents = Array.from(
                    componentsSection.querySelectorAll('input[name$="-component_id"]')
                ).some((field) => field.value);
                const hasRecipeErrors = Boolean(
                    componentsSection.querySelector(".field-error")
                );
                componentsSection.hidden = (
                    !shouldShow && !hasPersistedComponents && !hasRecipeErrors
                );
            }
        }
    }

    saleForm?.addEventListener("change", updateOptionalFields);
    inventoryRole?.addEventListener("change", updateOptionalFields);
    updateOptionalFields();
});
