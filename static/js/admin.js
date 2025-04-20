document.addEventListener("DOMContentLoaded", function () {
  // Toggle mobile menu
  const menuToggle = document.querySelector(".menu-toggle");
  const navLinks = document.querySelector(".nav-links");

  if (menuToggle && navLinks) {
    menuToggle.addEventListener("click", function () {
      navLinks.classList.toggle("active");
    });
  }

  // Set active link based on current page
  const currentPath = window.location.pathname;
  const navItems = document.querySelectorAll(".nav-links a");

  navItems.forEach((item) => {
    const href = item.getAttribute("href");
    if (
      currentPath === href ||
      (href !== "/" && currentPath.startsWith(href))
    ) {
      item.classList.add("active");
    }
  });
});
