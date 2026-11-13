/* Mejora progresiva: la clave permanece oculta si JavaScript no está disponible. */
(() => {
  const boton = document.querySelector("[data-visibilidad-clave]");
  if (!boton) return;
  const campo = document.getElementById(boton.getAttribute("aria-controls"));
  if (!campo) return;

  boton.hidden = false;
  boton.addEventListener("click", () => {
    const visible = campo.type === "password";
    campo.type = visible ? "text" : "password";
    boton.textContent = visible ? "Ocultar" : "Mostrar";
    boton.setAttribute("aria-label", visible ? "Ocultar clave" : "Mostrar clave");
  });
})();
