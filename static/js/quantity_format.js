(function () {
    // Preview only: persisted calculations remain server-side with Decimal.
    function formatDecimal(value) {
        if (!Number.isFinite(value)) return "—";
        return value.toLocaleString("pt-BR", {
            minimumFractionDigits: 0,
            maximumFractionDigits: 6,
        });
    }

    function formatQuantity(value, baseUnit) {
        if (!Number.isFinite(value)) return "—";
        let displayValue = value;
        let displayUnit = baseUnit;
        if (baseUnit === "g" && Math.abs(value) >= 1000) {
            displayValue = value / 1000;
            displayUnit = "kg";
        } else if (baseUnit === "mL" && Math.abs(value) >= 1000) {
            displayValue = value / 1000;
            displayUnit = "L";
        } else if (baseUnit === "unit") {
            displayUnit = "un";
        }
        return `${formatDecimal(displayValue)} ${displayUnit}`.trim();
    }

    function formatPercentage(value) {
        if (!Number.isFinite(value)) return "—";
        return `${value.toLocaleString("pt-BR", {
            minimumFractionDigits: 0,
            maximumFractionDigits: 1,
        })}%`;
    }

    function formatCurrency(value) {
        if (!Number.isFinite(value)) return "—";
        return new Intl.NumberFormat("pt-BR", {
            style: "currency",
            currency: "BRL",
        }).format(value);
    }

    window.BarFormatting = Object.freeze({
        formatCurrency,
        formatDecimal,
        formatPercentage,
        formatQuantity,
    });
})();
