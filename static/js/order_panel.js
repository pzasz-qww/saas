const mobileColumnButtons = document.querySelectorAll(".mobile-column-button");

mobileColumnButtons.forEach((button) => {
    button.addEventListener("click", () => {
        const target = document.getElementById(button.dataset.target);

        if (!target) {
            return;
        }

        target.scrollIntoView({
            behavior: "smooth",
            block: "nearest",
            inline: "start",
        });

        mobileColumnButtons.forEach((item) => item.classList.remove("active"));
        button.classList.add("active");
    });
});
