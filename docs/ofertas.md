# Ofertas, precios e impuestos · FR-GDS-28 · B10

Desde el detalle de una cotización abra **Registrar o actualizar oferta** junto al
proveedor invitado. Solo Administrador y Desarrollador pueden registrar, consultar
o descargar ofertas. Los usuarios del portal no tienen acceso a estas pantallas.

## Proveedores y captura

Se mantiene una oferta por proveedor/NIT y cotización. Cada guardado crea una revisión
histórica; no aparecen varias ofertas simultáneas del mismo proveedor al comparar.
La identidad queda fija, con NIT y razón social copiados de la invitación.

Los proveedores nuevos deben tener primero una ficha registrada. Se reutiliza el
formulario **Nuevo proveedor**, en lugar de crear fichas mínimas que omitan los
controles existentes. Una cotización manual permite invitar proveedores registrados
desde su detalle, respetando el límite D-10 actual. Las que provienen de una lista
cerrada conservan exclusivamente los proveedores elegidos de ese cierre.

Complete contacto, correo, teléfono, fecha de oferta y, opcionalmente, fecha final
de vigencia y observación. La vigencia no puede terminar antes de la fecha de oferta;
si no se indica, se muestra expresamente sin fecha, sin inventar una vigencia de negocio.

Para cada especificación capture precio unitario y tarifa de impuesto. El precio
admite cero y hasta cuatro decimales. La cantidad y unidad se toman de la línea de
cotización, con una foto de descripción/especificación. Se exige responder todas las
líneas una sola vez y no se admiten líneas ni invitaciones de otra cotización.

Se puede guardar mientras la cotización esté en borrador o en comparación. Decidida
y anulada son de solo lectura. El guardado no decide la cotización ni crea órdenes.

## Tarifas configurables D-11

En **Compras → Tarifas de impuesto** puede crear, editar o desactivar tarifas, con
nombre, porcentaje entre 0 y 100 y motivo. El porcentaje admite cuatro decimales.
La migración incluye únicamente **Exento/No gravado, 0 %**. No se carga IVA fijo ni
se presume qué tarifa corresponde a cada producto; debe seleccionarla expresamente.

Cada línea de oferta conserva nombre y porcentaje aplicados. Cambiar el catálogo
no modifica ofertas guardadas o revisiones anteriores. Un guardado nuevo exige
tarifas activas y recalcula con sus porcentajes actuales.

## Importes reproducibles

Configure en **Configuración → Parámetros**:

| Parámetro | Inicial | Alternativas |
| --- | --- | --- |
| `cotizacion.decimales_importes` | 0, pesos enteros | 1 o 2 decimales |
| `cotizacion.modo_redondeo` | ROUND_HALF_UP | ROUND_HALF_EVEN, ROUND_DOWN, ROUND_UP |

Son reglas provisionales D-11, pendientes de aprobación de la clínica. El servicio
usa Decimal, nunca flotantes binarios para precios, cantidades o porcentajes:

1. Subtotal de línea = cantidad × precio, redondeado según el parámetro.
2. Impuesto = subtotal ya redondeado × porcentaje / 100, redondeado.
3. Total de línea = subtotal + impuesto.
4. El encabezado suma subtotales e impuestos de líneas y calcula su total.

No se aceptan totales del navegador ni se aplican descuentos implícitos. Cada
guardado conserva las reglas utilizadas. Cambiar parámetros no recalcula registros
existentes; se recalculan cuando el operador guarda de nuevo la oferta.

Ejemplo ficticio probado, sin representar una tarifa oficial:

| Cantidad | Precio | Tarifa ficticia | Decimales | Subtotal | Impuesto | Total |
| --- | --- | --- | --- | --- | --- | --- |
| 2,5 | 100,15 | 0 % | 0 | 250 | 0 | 250 |
| 2,5 | 100,15 | 19 % | 0 | 250 | 48 | 298 |
| 2,5 | 100,15 | 19 % | 2 | 250,38 | 47,57 | 297,95 |

La captura muestra el último total guardado por separado; guarde para recalcular
con los precios del formulario. Un número de revisión detecta ediciones concurrentes
y exige recargar si otro guardado ya cambió la oferta.

## PDF privado e historial

Puede adjuntar un PDF opcional. Se reutilizan los controles existentes: extensión
PDF, cabecera `%PDF-`, archivo no vacío y máximo 10 MB. Se almacena con UUID en
el área privada, sin URL pública ni ruta física en las pantallas.

Reemplazar o retirar el PDF actual conserva los archivos y revisiones anteriores.
El detalle permite consultar cada revisión con contacto, reglas, especificaciones,
precios, tarifas, resultados, actor, motivo y PDF que sustentaba ese guardado.
Las revisiones y adjuntos anteriores no se editan ni eliminan.

La descarga exige rol administrativo y comprueba cotización, oferta y adjunto.
Usa respuesta de descarga PDF, `nosniff`, sin caché y bitácora. No se puede descargar
un adjunto de otra oferta cambiando identificadores en la URL.

El guardado es transaccional. Si falla validación o auditoría, se revierten importes,
oferta, revisión y adjunto; se elimina exclusivamente el archivo nuevo que no llegó
a confirmarse. Los PDF anteriores permanecen intactos. Las cargas de archivos
rechazan transacciones externas para evitar huérfanos tras una reversión posterior.

## Verificación

Veintidós pruebas nuevas en `compras/tests_ofertas.py` comprueban ejemplos manuales
de cálculo, redondeos, tarifas distintas y exentos, valores inválidos, vigencia,
separación de oferentes/cotizaciones, unicidad e historial, bloqueo de edición,
límites de invitación, PDF privados, permisos, CSRF y compensación de archivos.

B11 incorpora la [matriz de verificaciones](verificaciones_ofertas.md), con estados,
responsable, fecha e historial de evidencia. Guardar otra revisión de la oferta
marca las verificaciones anteriores para revisar y reconfirmar, conservando su estado.

B12 añade la [justificación del caso de proveedor único](proveedor_unico_cotizacion.md),
sugerida por una sola oferta y confirmada expresamente con causal y evidencia.

B13 incorpora el [comparativo y decisión](decision_cotizacion.md). Las ofertas se
conservan en la foto propuesta; cambiar una mientras se aprueba exige anular y
crear otra propuesta. Una cotización decidida solo admite cambios tras anular su decisión.

B14 incorpora [contratos y pólizas](contratos_polizas.md) cuando la compra los requiere.

B15 copia los datos adjudicados y la revisión conservada a [órdenes por proveedor](ordenes_compra.md),
sin depender de precios o catálogos actuales.

Siguiente etapa: **B17, cálculo configurable de importes de la orden**.
