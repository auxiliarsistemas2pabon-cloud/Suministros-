"use strict";

(() => {
  const filas = document.getElementById("lineas-cotizacion");
  const plantilla = document.getElementById("linea-cotizacion-vacia");
  const boton = document.getElementById("agregar-linea-cotizacion");
  const total = document.getElementById("id_lineas-TOTAL_FORMS");
  if (!filas || !plantilla || !boton || !total) return;
  const limite = Number(filas.dataset.limite);
  const activas = () => [...filas.querySelectorAll("fieldset[data-linea]")].filter(fila => !fila.querySelector('input[name$="-DELETE"]')?.checked).length;
  const actualizar = () => { boton.disabled = limite > 0 && activas() >= limite; };
  boton.hidden = false;
  actualizar();
  filas.addEventListener("change", actualizar);
  boton.addEventListener("click", () => {
    if (limite > 0 && activas() >= limite) return;
    const indice = Number(total.value);
    filas.insertAdjacentHTML("beforeend", plantilla.innerHTML.replaceAll("__prefix__", String(indice)));
    total.value = String(indice + 1);
    actualizar();
  });
})();
