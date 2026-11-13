"use strict";

(() => {
  const boton = document.getElementById("agregar-origen");
  const total = document.getElementById("id_origenes-TOTAL_FORMS");
  const maximo = document.getElementById("id_origenes-MAX_NUM_FORMS");
  const plantilla = document.getElementById("origen-vacio");
  const filas = document.getElementById("origenes-filas");
  if (!boton || !total || !plantilla || !filas) return;
  boton.hidden = false;
  boton.addEventListener("click", () => {
    const indice = Number(total.value);
    const limite = Number(maximo.value);
    if (indice >= limite) return;
    const contenido = plantilla.innerHTML.replaceAll("__prefix__", String(indice));
    filas.insertAdjacentHTML("beforeend", contenido);
    total.value = String(indice + 1);
    boton.disabled = indice + 1 >= limite;
  });
})();
