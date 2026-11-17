/* Cálculos de comodidad para la tabla de líneas; el servidor sigue siendo la autoridad. */
(function () {
  "use strict";

  function numero(valor) {
    var normalizado = String(valor || "").replace(",", ".");
    var resultado = Number(normalizado);
    return Number.isFinite(resultado) && resultado >= 0 ? resultado : 0;
  }

  function totalInformado(valor) {
    // El total del archivo no pasa por Number: conserva sus dos decimales exactos.
    var texto = String(valor).trim().replace(",", ".");
    if (!/^\d+(?:\.\d{0,2})?$/.test(texto)) return "Pendiente de validar";
    var partes = texto.split(".");
    var entero = partes[0].replace(/^0+(?=\d)/, "");
    return entero.replace(/\B(?=(\d{3})+(?!\d))/g, ".") + "," + ((partes[1] || "") + "00").slice(0, 2);
  }

  function calcular(fila) {
    var total = 0;
    fila.querySelectorAll("[data-cantidad]").forEach(function (campo) {
      total += numero(campo.value);
    });
    var precioCampo = fila.querySelector("[data-precio]");
    var precio = numero(precioCampo ? precioCampo.value : 0);
    var informadoCampo = fila.querySelector("[data-costo-informado]");
    var informado = informadoCampo && informadoCampo.value.trim() !== "";
    var totalCampo = fila.querySelector("[data-total]");
    var costoCampo = fila.querySelector("[data-costo]");
    if (totalCampo) totalCampo.textContent = String(total);
    if (costoCampo) costoCampo.textContent = informado ? totalInformado(informadoCampo.value) : (total * precio).toLocaleString("es-CO", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }

  function activarFila(fila) {
    if (!fila) return;
    fila.querySelectorAll("[data-cantidad], [data-precio], [data-costo-informado]").forEach(function (campo) {
      campo.addEventListener("input", function () { calcular(fila); });
      campo.addEventListener("change", function () { calcular(fila); });
    });
    calcular(fila);
  }

  var formulario = document.getElementById("formulario-lineas");
  if (!formulario) return;
  formulario.querySelectorAll("[data-linea]").forEach(activarFila);
  var boton = document.getElementById("agregar-linea");
  var plantilla = document.getElementById("linea-vacia");
  var totalFormularios = document.getElementById("id_" + formulario.dataset.prefix + "-TOTAL_FORMS");
  if (!boton || !plantilla || !totalFormularios) return;
  boton.addEventListener("click", function () {
    var indice = Number(totalFormularios.value);
    var fragmento = plantilla.content.cloneNode(true);
    fragmento.querySelectorAll("[name], [id], [for]").forEach(function (elemento) {
      ["name", "id", "for"].forEach(function (atributo) {
        if (elemento.hasAttribute(atributo)) elemento.setAttribute(atributo, elemento.getAttribute(atributo).replace(/__prefix__/g, indice));
      });
    });
    var fila = fragmento.querySelector("[data-linea]");
    document.getElementById("lineas-contenedor").appendChild(fragmento);
    totalFormularios.value = indice + 1;
    activarFila(fila);
  });
})();
