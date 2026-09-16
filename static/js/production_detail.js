(function () {
    const dialog = document.getElementById("reversal-dialog");
    const openButton = document.getElementById("open-reversal-dialog");
    const cancelButton = document.getElementById("cancel-reversal");
    if (!dialog || !openButton || !cancelButton) return;

    openButton.addEventListener("click", () => dialog.showModal());
    cancelButton.addEventListener("click", () => dialog.close());
    dialog.addEventListener("click", event => {
        if (event.target === dialog) dialog.close();
    });
})();
