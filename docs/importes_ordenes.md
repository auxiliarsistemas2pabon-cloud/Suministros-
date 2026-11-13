# B17 · Importes de órdenes

La copia inicial conserva exactamente lo adjudicado, con las reglas Decimal de su
oferta. Solo se modifica un borrador con decisión aprobada vigente, motivo y revisión
actual. El cálculo se realiza en el servidor; el formulario no recibe totales ni
porcentajes libres. La oferta, adjudicación y valores originales permanecen intactos.

## Descuentos, impuestos y redondeo

En **Compras → Órdenes de compra → Editar borrador**, indique el descuento en dinero
por línea, no como porcentaje. Debe ser no negativo, con máximo dos decimales, y no
superar cantidad × precio. Puede cambiar la tarifa seleccionando una activa del
catálogo de impuestos. La opción vacía conserva el nombre y porcentaje guardados,
aunque el catálogo haya cambiado o desactivado esa tarifa.

En **Configuración → Parámetros** se encuentran estas reglas provisionales D-11:

| Parámetro | Inicial | Opciones |
| --- | --- | --- |
| `orden.orden_descuento` | `antes_impuesto` | `antes_impuesto`, `despues_impuesto` |
| `orden.nivel_redondeo` | `linea` | `linea`, `total` |
| `orden.decimales_importes` | `0` | `0`, `1`, `2` |
| `orden.modo_redondeo` | `ROUND_HALF_UP` | `ROUND_HALF_UP`, `ROUND_HALF_EVEN`, `ROUND_DOWN`, `ROUND_UP` |

Marque **Aplicar parámetros actuales de importes y actualizar las retenciones
seleccionadas** para adoptar esos valores en el borrador. Un cambio de parámetros
por sí solo no recalcula documentos. Sin esa opción se conserva la receta guardada.
Cambiar una tarifa de línea requiere seleccionarla expresamente.

El bruto es cantidad × precio; la base neta es bruto − descuento. Antes del impuesto
se grava la base neta; después del impuesto se grava el bruto y se resta el descuento
al total con impuestos. Cada tarifa se guarda por línea. No se presupone IVA fijo.

Con redondeo por línea, se redondean bruto y descuento, y se calcula y redondea el
impuesto sobre esa base. Con redondeo al total, se suman los brutos, descuentos e
impuestos sin redondear y luego se redondea cada suma. Se distribuyen sus unidades
de redondeo según los mayores residuos, empatando por posición de línea. El descuento
distribuido nunca supera el bruto asignado; si su línea no tiene capacidad, el residuo
pasa a la siguiente con capacidad. El desglose diferencia descuento solicitado y
aplicado. Así, las líneas suman exactamente la cabecera, sin un ajuste oculto.

## Retenciones

**Compras → Retenciones de órdenes** permite crear y editar nombre, porcentaje de
0 a 100, base mínima opcional, base de cálculo y estado activo. El catálogo comienza
vacío. Los cambios exigen motivo y quedan en bitácora; no se borran tipos desde la
interfaz. Configure únicamente tasas acordadas con financiera.

Seleccione las retenciones en el borrador. La base puede ser neta después del
descuento, subtotal bruto o total con impuestos. El umbral es inclusivo: base igual
al mínimo sí aplica. Una selección bajo el mínimo queda registrada, con importe cero
y explicación. Cada retención se calcula sobre la base indicada de la cabecera y se
redondea con la receta de la orden. No se calcula una retención sobre otra.

Las seleccionadas conservan nombre, porcentaje, mínimo y tipo de base. Editar otra
parte de la orden recalcula su importe sobre la nueva base, usando esos datos guardados.
Una retención nueva usa el catálogo activo. Una retención guardada e inactiva puede
conservarse o retirarse; para actualizarla debe estar activa. La suma retenida no puede
superar el total con impuestos.

Total antes de retenciones = base neta + impuestos.
Total a pagar = total antes de retenciones − retenciones.

## Emisión e historia

El motor B16 valida todos los importes contra las recetas y retenciones guardadas
antes de reservar número. Una inconsistencia impide emitir y no consume consecutivo.
Conserva una foto de cantidades, precios, descuentos, tarifas, retenciones, reglas y
totales al emitir. Cambios posteriores de catálogos no afectan esa foto ni los
importes emitidos. Anular conserva la misma información. La autorización y la
emisión desde la interfaz corresponden a **B18**.

Las revisiones muestran el desglose y reglas de cada guardado. Las migraciones añaden
las bases derivadas a órdenes previas conservando importes, originales y revisiones;
no inventan una foto de emisión histórica para documentos anteriores a B17.

## Casos fijos de referencia

Todos son ficticios, con dos decimales y ROUND_HALF_UP salvo donde se indique.
**Pendiente de validar con financiera**: sustituir estos ejemplos por casos aprobados.

| Caso | Bruto | Descuento | Impuesto | Retención | Total |
| --- | ---: | ---: | ---: | ---: | ---: |
| Tarifa ficticia 19 % | 100 | 0 | 19 | 0 | 119 |
| Exento | 100 | 0 | 0 | 0 | 100 |
| Descuento 10 antes del impuesto ficticio 19 % | 100 | 10 | 17,10 | 0 | 107,10 |
| Descuento 10 después del impuesto ficticio 19 % | 100 | 10 | 19 | 0 | 109 |
| Anterior antes + línea exenta de 50 | 150 | 10 | 17,10 | 0 | 157,10 |
| Base neta 90, retención ficticia 2,5 %, mínimo 90 | 100 | 10 | 17,10 | 2,25 | 104,85 |
| Mismo caso, mínimo 90,01 | 100 | 10 | 17,10 | 0 | 107,10 |
| Tres líneas exentas de 0,005; por línea | 0,03 | 0 | 0 | 0 | 0,03 |
| Mismas tres líneas; al total | 0,02 | 0 | 0 | 0 | 0,02 |

Los resultados técnicos están en [avances](avances.md). El cumplimiento contable de
los casos oficiales sigue pendiente de validación de financiera (D-11).

Aprobación/emisión, PDF directo, recepción y seguimiento completados técnicamente:
[guía de los flujos B18–B27](aprobacion_recepcion_seguimientos.md).
La preparación de Ubuntu está en [despliegue](despliegue.md).
