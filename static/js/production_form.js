(function () {
    const { formatDecimal, formatQuantity } = window.BarFormatting;
    const planned = document.getElementById("id_planned_quantity");
    const produced = document.getElementById("id_produced_quantity");
    if (!planned || !produced) return;

    const parseInputNumber = (value) => {
        const normalized = String(value || "").trim().replace(",", ".");
        return normalized === "" ? Number.NaN : Number(normalized);
    };

    document.querySelectorAll(".production-component").forEach((row) => {
        const input = row.querySelector("[name$='-actual_quantity']");
        const lossInput = row.querySelector("[name$='-loss_quantity']");
        if (!input) return;
        const plannedValue = parseInputNumber(planned.value);
        const currentValue = parseInputNumber(input.value);
        const theoretical = plannedValue * parseInputNumber(row.dataset.perUnit);
        input.dataset.synced = (
            Number.isFinite(currentValue)
            && Number.isFinite(theoretical)
            && Math.abs(currentValue - theoretical) < 0.0000005
        ) ? "true" : "false";
        input.addEventListener("input", () => {
            input.dataset.synced = "false";
            updatePhysicalInputPreviews(row);
        });
        lossInput?.addEventListener("input", () => updatePhysicalInputPreviews(row));
    });

    function updatePhysicalInputPreviews(row) {
        const baseUnit = row.dataset.baseUnit;
        const actual = row.querySelector("[name$='-actual_quantity']");
        const loss = row.querySelector("[name$='-loss_quantity']");
        const actualDisplay = row.querySelector("[data-actual-display]");
        const lossDisplay = row.querySelector("[data-loss-display]");
        const actualValue = parseInputNumber(actual?.value);
        const lossValue = parseInputNumber(loss?.value);
        if (actualDisplay) actualDisplay.textContent = formatQuantity(actualValue, baseUnit);
        if (lossDisplay) lossDisplay.textContent = formatQuantity(lossValue, baseUnit);
    }

    function update() {
        const plannedValue = parseInputNumber(planned.value);
        const producedValue = parseInputNumber(produced.value);
        document.getElementById("planned-yield").textContent = formatDecimal(plannedValue);
        document.getElementById("actual-yield").textContent = formatDecimal(producedValue);
        document.getElementById("yield-percentage").textContent = plannedValue > 0
            ? `${formatDecimal((producedValue * 100) / plannedValue)}%`
            : "—";
        document.getElementById("yield-difference").textContent = formatDecimal(plannedValue - producedValue);

        document.querySelectorAll(".production-component").forEach((row) => {
            const theoretical = plannedValue * parseInputNumber(row.dataset.perUnit);
            const output = row.querySelector("[data-theoretical]");
            const actual = row.querySelector("[name$='-actual_quantity']");
            if (output) output.textContent = formatQuantity(theoretical, row.dataset.baseUnit);
            if (
                actual
                && actual.dataset.synced === "true"
                && Number.isFinite(theoretical)
            ) actual.value = theoretical;
            updatePhysicalInputPreviews(row);
        });
    }

    planned.addEventListener("input", update);
    produced.addEventListener("input", update);
    update();
})();
