(function () {
    const { formatDecimal, formatQuantity } = window.BarFormatting;
    const form = document.getElementById("production-form");
    const planned = document.getElementById("id_planned_quantity");
    const produced = document.getElementById("id_produced_quantity");
    const previewButton = document.getElementById("preview-production");
    if (!form || !planned || !produced || !previewButton) return;

    const previewRows = Array.from(document.querySelectorAll(".production-component--preview"));
    const advancedRows = Array.from(document.querySelectorAll(".production-component--advanced"));
    const parseInputNumber = (value) => {
        const normalized = String(value || "").trim().replace(",", ".");
        return normalized === "" ? Number.NaN : Number(normalized);
    };
    const inputDecimal = (value) => {
        if (!Number.isFinite(value)) return "";
        return value.toFixed(6).replace(/0+$/, "").replace(/\.$/, "");
    };

    produced.dataset.synced = (
        produced.value.trim() === ""
        || Math.abs(parseInputNumber(produced.value) - parseInputNumber(planned.value)) < 0.0000005
    ) ? "true" : "false";

    advancedRows.forEach(row => {
        const actual = row.querySelector("[name$='-actual_quantity']");
        const loss = row.querySelector("[name$='-loss_quantity']");
        if (!actual) return;
        const theoretical = parseInputNumber(planned.value) * parseInputNumber(row.dataset.perUnit);
        const current = parseInputNumber(actual.value);
        actual.dataset.synced = (
            actual.value.trim() === ""
            || (Number.isFinite(theoretical) && Math.abs(current - theoretical) < 0.0000005)
        ) ? "true" : "false";
        actual.addEventListener("input", () => {
            actual.dataset.synced = "false";
            invalidateSummary();
            update();
        });
        loss?.addEventListener("input", () => {
            invalidateSummary();
            update();
        });
    });

    function invalidateSummary() {
        const summary = document.querySelector("[data-production-summary]");
        const confirm = document.querySelector("[data-production-confirm]");
        if (summary) summary.hidden = true;
        if (confirm) confirm.disabled = true;
    }

    function updatePhysicalInputPreviews(row) {
        const baseUnit = row.dataset.baseUnit;
        const actual = row.querySelector("[name$='-actual_quantity']");
        const loss = row.querySelector("[name$='-loss_quantity']");
        const actualDisplay = row.querySelector("[data-actual-display]");
        const lossDisplay = row.querySelector("[data-loss-display]");
        if (actualDisplay) actualDisplay.textContent = formatQuantity(parseInputNumber(actual?.value), baseUnit);
        if (lossDisplay) lossDisplay.textContent = formatQuantity(parseInputNumber(loss?.value), baseUnit);
    }

    function update() {
        const plannedValue = parseInputNumber(planned.value);
        if (produced.dataset.synced === "true" && Number.isFinite(plannedValue)) {
            produced.value = inputDecimal(plannedValue);
        }
        const producedValue = parseInputNumber(produced.value);

        document.getElementById("planned-yield").textContent = formatDecimal(plannedValue);
        document.getElementById("actual-yield").textContent = formatDecimal(producedValue);
        document.getElementById("yield-percentage").textContent = plannedValue > 0 && producedValue > 0
            ? `${formatDecimal((producedValue * 100) / plannedValue)}%`
            : "—";

        let allComponentsValid = previewRows.length > 0;
        previewRows.forEach((row, index) => {
            const advancedRow = advancedRows[index];
            const actual = advancedRow?.querySelector("[name$='-actual_quantity']");
            const loss = advancedRow?.querySelector("[name$='-loss_quantity']");
            const perUnit = parseInputNumber(row.dataset.perUnit);
            const available = parseInputNumber(row.dataset.available);
            const theoretical = plannedValue * perUnit;
            if (actual?.dataset.synced === "true" && Number.isFinite(theoretical)) {
                actual.value = inputDecimal(theoretical);
            }
            const actualValue = parseInputNumber(actual?.value);
            const lossValue = parseInputNumber(loss?.value);
            const requirement = row.querySelector("[data-theoretical]");
            const advancedRequirement = advancedRow?.querySelector("[data-advanced-theoretical]");
            const status = row.querySelector("[data-component-status]");
            const theoreticalDisplay = formatQuantity(theoretical, row.dataset.baseUnit);
            if (requirement) requirement.textContent = theoreticalDisplay;
            if (advancedRequirement) advancedRequirement.textContent = theoreticalDisplay;

            status.classList.remove("component-status--ok", "component-status--error");
            const quantitiesValid = (
                Number.isFinite(theoretical)
                && theoretical > 0
                && Number.isFinite(actualValue)
                && actualValue > 0
                && Number.isFinite(lossValue)
                && lossValue >= 0
                && lossValue <= actualValue
            );
            if (!quantitiesValid) {
                status.textContent = "Informe a quantidade";
                allComponentsValid = false;
            } else if (actualValue > available) {
                status.textContent = "Insuficiente";
                status.classList.add("component-status--error");
                allComponentsValid = false;
            } else {
                status.textContent = "Disponível";
                status.classList.add("component-status--ok");
            }
            if (advancedRow) updatePhysicalInputPreviews(advancedRow);
        });

        previewButton.disabled = !(
            plannedValue > 0
            && producedValue > 0
            && allComponentsValid
        );
    }

    planned.addEventListener("input", () => {
        invalidateSummary();
        update();
    });
    produced.addEventListener("input", () => {
        produced.dataset.synced = "false";
        invalidateSummary();
        update();
    });
    form.querySelectorAll("input, textarea").forEach(input => {
        if (input === planned || input === produced || input.name.endsWith("-actual_quantity") || input.name.endsWith("-loss_quantity")) return;
        input.addEventListener("input", invalidateSummary);
        input.addEventListener("change", invalidateSummary);
    });

    update();
})();
