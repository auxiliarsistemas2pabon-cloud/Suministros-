# Cierre y transición de listas de elegibles · B8

Desde **Compras → Lista** puede cerrar, reabrir o anular con rol Administrador o
Desarrollador. Cada acción exige motivo, comprueba el estado actual en servidor
y se registra en la bitácora. Coordinador y Proveedor no tienen acceso.

## Cerrar

Complete las calificaciones, registre una decisión vigente y revise el estado
documental. En el detalle indique motivo y, si corresponde, justificación documental;
seleccione **Cerrar lista**.

Dentro de una sola transacción, el servidor bloquea la necesidad y la lista,
comprueba B5–B6 y vuelve a comprobar B7 con la fecha actual de Bogotá:

- Calificaciones completas y versión de criterios asignada.
- Decisión vigente, selección con cantidad positiva y justificaciones de proveedor
  único, exceso de cantidad y elecciones excepcionales cuando correspondan.
- Reglas documentales actuales: advertir con justificación o bloquear según la
  configuración. Una justificación no evita un bloqueo.

El cierre guarda usuario y fecha/hora, pasa a solo lectura y conserva resultados,
criterios, escala/método, puestos, desempates, cantidades, decisión y origen de la
necesidad. También fija la referencia FR14 y la foto documental de B7. Un error de
validación, captura o archivo histórico revierte todo, incluida la bitácora parcial.
Las reglas provisionales D-05/D-07/D-08 no se convierten en aprobaciones clínicas
por cerrar técnicamente una lista.

Cerrar no crea cotizaciones ni órdenes. Cada cierre genera un registro en el
**Historial de cierres**, con motivo y una copia completa que no se edita ni elimina.
Puede abrirlo para consultar resultados y documentos de ese ciclo.

## Consultar una lista cerrada

Las matrices, puestos y exportación leen la foto conservada. Modificar parámetros,
registrar otra evaluación o cambiar fuentes después no recalcula el cierre. El
Excel también usa el objeto y área conservados, además de la foto documental.
Los servicios de participantes, calificaciones, decisiones y documentos rechazan
modificaciones mientras la lista está cerrada o anulada.

Las listas anteriores sin cierre completo se identifican expresamente. No se
inventan usuario, fecha ni resultados históricos. Deben reabrirse, revisarse y
cerrarse para preparar la cotización, si no tienen una asociación que lo impida.

## Reabrir

**Reabrir lista** solo admite estado cerrado y ausencia de cotización asociada.
Guarda usuario, fecha y motivo de reapertura. Conserva los cierres archivados,
libera las fotos activas de resultados/documentos y vuelve a borrador.

Las respuestas, cantidades y observaciones permanecen para revisión. La decisión
se invalida y la justificación documental debe renovarse si corresponde. Los
desempates siguen disponibles mientras no cambien sus calificaciones/participantes;
los controles existentes los invalidan cuando eso ocurre. Antes de cerrar otra vez,
registre la decisión y revise los documentos actuales. El siguiente cierre crea
otro archivo, sin sobrescribir el anterior.

## Anular

Puede anular un borrador sin exigir que esté completo, o una lista cerrada sin
cotización asociada. Se guardan usuario, fecha y motivo de anulación. Los datos y
cierres anteriores permanecen disponibles; la lista anulada no se edita ni reabre.
La asociación a cotización bloquea también la anulación para conservar su origen.

El listado de necesidades muestra cada lista con estado **Borrador**, **Cerrada**,
**Con cotización** o **Anulada**, separado del estado de la necesidad.

## Preparar cotización sin crearla

**Iniciar cotización** aparece solo con la lista cerrada y abre una vista de
preparación con la necesidad, líneas de origen y proveedores con cantidad autorizada
mayor que cero. Los datos se toman del cierre conservado. B9 añade el formulario
de creación; no hay guardado automático al cerrar ni al abrir la precarga.

La URL `compras:cotizacion_iniciar` y el servicio
`cotizacion_origen.preparar_cotizacion` se integran con el formulario B9. El servicio
de precarga sigue siendo de consulta y comprueba que la lista continúe cerrada y
tenga foto completa antes de devolver los datos.

### Contrato de integración para B9

El detector `cotizacion_origen.hay_cotizacion` consulta el modelo `compras.Cotizacion`
mediante `lista_elegibles_id`. B9 conserva ese FK y bloquea la lista al crear la
asociación, antes de comprobar que siga cerrada. Así, crear una
cotización y reabrir se serializan sobre la misma fila. Cualquier asociación impide
reabrir/anular, incluso si esa cotización está anulada.

La prueba inicial de B8 usa una asociación simulada a través del adaptador. B9
añade el modelo y la comprobación del bloqueo con una cotización real; consulte
la [guía de cotizaciones](cotizaciones.md).

## Verificación

Dieciséis pruebas nuevas en `compras/tests_cierre.py` cubren cierre con actor/fecha,
validadores, atomicidad, archivo inmutable, reapertura y segundo cierre, anulación,
asociación a cotización, lectura de la foto, desempates, Excel, precarga sin
escrituras, estados del listado, permisos, CSRF y métodos HTTP.

Siguiente etapa: **B10, ofertas, precios e impuestos por proveedor**.
