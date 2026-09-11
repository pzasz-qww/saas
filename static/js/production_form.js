(function () {
    const planned = document.getElementById("id_planned_quantity");
    const produced = document.getElementById("id_produced_quantity");
    if (!planned || !produced) return;

    const format = (value) => {
        if (!Number.isFinite(value)) return "—";
        return value.toLocaleString("pt-BR", { maximumFractionDigits: 6 });
    };

    document.querySelectorAll(".production-component").forEach((row) => {
        const input = row.querySelector("[name$='-actual_quantity']");
        if (!input) return;
        const plannedValue = Number(String(planned.value).replace(",", "."));
        const currentValue = Number(String(input.value).replace(",", "."));
        const theoretical = plannedValue * Number(row.dataset.perUnit);
        input.dataset.synced = (
            Number.isFinite(currentValue)
            && Number.isFinite(theoretical)
            && Math.abs(currentValue - theoretical) < 0.0000005
        ) ? "true" : "false";
        input.addEventListener("input", () => { input.dataset.synced = "false"; });
    });

    function update() {
        const plannedValue = Number(String(planned.value).replace(",", "."));
        const producedValue = Number(String(produced.value).replace(",", "."));
        document.getElementById("planned-yield").textContent = format(plannedValue);
        document.getElementById("actual-yield").textContent = format(producedValue);
        document.getElementById("yield-percentage").textContent = plannedValue > 0
            ? `${format((producedValue * 100) / plannedValue)}%`
            : "—";
        document.getElementById("yield-difference").textContent = format(plannedValue - producedValue);

        document.querySelectorAll(".production-component").forEach((row) => {
            const theoretical = plannedValue * Number(row.dataset.perUnit);
            const output = row.querySelector("[data-theoretical]");
            const actual = row.querySelector("[name$='-actual_quantity']");
            if (output) output.textContent = format(theoretical);
            if (actual && actual.dataset.synced === "true") actual.value = theoretical;
        });
    }

    planned.addEventListener("input", update);
    produced.addEventListener("input", update);
    update();
})();
