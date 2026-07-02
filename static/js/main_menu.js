const mainDropdownMenu = document.getElementById("mainDropdownMenu");
const mainMenuButton = document.querySelector(".menu-button");

if (mainDropdownMenu && mainMenuButton) {
    mainMenuButton.addEventListener("click", () => {
        mainDropdownMenu.classList.toggle("open");
    });

    document.addEventListener("click", event => {
        const clickedInsideMenu = mainDropdownMenu.contains(event.target);
        const clickedButton = mainMenuButton.contains(event.target);

        if (!clickedInsideMenu && !clickedButton) {
            mainDropdownMenu.classList.remove("open");
        }
    });
}
