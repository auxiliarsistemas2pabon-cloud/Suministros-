/* Navegación adaptable. Los enlaces siguen disponibles cuando JavaScript no carga. */
(() => {
  const control = document.querySelector("[data-menu-control]");
  const menu = document.getElementById("menu-principal");
  if (!control || !menu) return;
  const movil = window.matchMedia("(max-width: 1023px)");
  const cambiar = (abierto) => {
    document.body.dataset.menuAbierto = String(abierto);
    control.setAttribute("aria-expanded", String(abierto));
  };
  document.body.classList.add("con-interfaz");
  cambiar(!movil.matches);
  control.addEventListener("click", () => cambiar(control.getAttribute("aria-expanded") !== "true"));
  document.addEventListener("keydown", (evento) => {
    if (evento.key === "Escape" && movil.matches && control.getAttribute("aria-expanded") === "true") {
      cambiar(false);
      control.focus();
    }
  });
  movil.addEventListener("change", () => cambiar(!movil.matches));
})();
