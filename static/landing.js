// Landing page: small script, no app logic
document.getElementById("footerYear").textContent = new Date().getFullYear();

const navMenu = document.getElementById("navMenu");
const navLinks = document.querySelector(".nav-links");
if (navMenu && navLinks) {
    navMenu.addEventListener("click", () => navLinks.classList.toggle("open"));
}

// Reveal-on-scroll for sections
const io = new IntersectionObserver((entries) => {
    entries.forEach((e) => {
        if (e.isIntersecting) e.target.classList.add("in");
    });
}, { threshold: 0.15 });
document.querySelectorAll(".section, .trust-bar, .cta-section").forEach((el) => io.observe(el));
