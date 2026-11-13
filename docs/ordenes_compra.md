# Órdenes desde la decisión aprobada · B15

Desde una decisión aprobada abra **Crear o consultar borradores por proveedor**.
Administración y Desarrolladores pueden preparar, crear, consultar y editar las
órdenes en borrador, con motivo y bitácora.

## Creación y copia de lo acordado

La decisión debe estar aprobada, conservar sus firmas y tener la cotización en
Decidida. Una propuesta pendiente, una decisión anulada o una cotización que ya
no está decidida no permiten generar órdenes.

Abrir la preparación muestra los proveedores y líneas sin escribir registros.
Al guardar se crea una orden en borrador por proveedor adjudicado. Si se adjudicó
la oferta completa, contiene todas sus líneas; por línea, cada proveedor recibe
únicamente las especificaciones que se le asignaron.

Repetir la creación devuelve las órdenes existentes. No duplica borradores ni
sobrescribe los que ya fueron editados. La operación completa es transaccional:
un error en cualquier proveedor revierte todas las órdenes del lote.

Se copia la identidad adjudicada del proveedor, el contacto de la revisión de
oferta aprobada, descripciones, unidades, cantidades, precios, tarifas, porcentajes
e importes. Los datos monetarios salen de la foto B13 y se contrastan con la revisión
inmutable B10; no se toman precios ni tarifas de registros actuales. Cambiar el
catálogo, la ficha del proveedor o el precio vivo no recalcula la orden.

Si hay contrato, las condiciones iniciales de pago proceden de su foto conservada
en la aprobación B14. Puede indicar condiciones de pago para el borrador con motivo.
El origen contractual se conserva por separado. Sin contrato ni condiciones
ofertadas se deja el texto vacío para completarlo, sin inventar plazos.

El borrador tiene fecha de elaboración y usuario que lo creó. La numeración al
emitir se prepara en [B16](consecutivos_ordenes.md); los borradores siguen sin número
oficial. La interfaz de emisión se integra en B18.

## Editar el borrador

Desde **Órdenes de compra → Orden → Editar borrador con motivo** puede cambiar
referencia, descripción, especificación, unidad, cantidad, precio, fecha de
elaboración y condiciones de pago. No se agregan ni eliminan especificaciones
adjudicadas ni se mezclan líneas de otras órdenes.

Cantidades y precios usan Decimal, con las escalas existentes de cotización/oferta.
La cantidad debe ser positiva y el precio no negativo. Se rechazan valores no
finitos, flotantes binarios y totales enviados por el cliente.

Al cambiar una línea se conserva su foto original y se muestran los valores
originales y actuales de cada diferencia, incluidos los importes recalculados.
Queda marcada con historial de modificación. Si restablece los valores originales,
la diferencia actual desaparece y se conserva la marca y las revisiones anteriores.
Una edición de orden no modifica la oferta ni la adjudicación originales.

Cada guardado exige motivo, registra usuario/fecha y conserva una revisión completa
inmutable. Una revisión esperada evita sobrescribir cambios posteriores a la
apertura del formulario. Un guardado sin cambios no crea revisiones nuevas.

La copia inicial conserva exactamente los importes adjudicados, la tarifa y las
reglas de la oferta. B17 permite descuentos en dinero por línea, selección explícita
de tarifas y retenciones, y adopción explícita de parámetros de cálculo actuales.
Los cambios de catálogo no sustituyen las fotos guardadas. Consulte el cálculo
y los ejemplos provisionales en la [guía de importes](importes_ordenes.md).

## Anulación de la decisión de origen

Si anula una decisión con órdenes todavía en borrador, esos borradores se anulan
en la misma transacción, con usuario, fecha, motivo e historial. Se conservan
líneas, importes, fotos y revisiones; ya no permiten edición ni creación desde esa
decisión. Una decisión nueva puede producir sus propias órdenes.

Si alguna orden avanzó del borrador, primero deberá resolver su anulación mediante
el flujo correspondiente. B15 impide anular la decisión dejando una orden avanzada
con origen invalidado. Los flujos de aprobación, emisión y recepción se desarrollan
en las etapas posteriores; aquí se preparan sus estados en el modelo.

## Trazabilidad

El detalle de la orden enlaza con decisión, cotización, proveedor, necesidad,
lista de elegibles y cierre exacto, contrato/pólizas, revisión conservada de oferta
y proyección de cada línea, cuando existen en el origen.

La evaluación FR14 proviene de la foto documental del cierre o de una verificación
documental confirmada de la oferta. Una evaluación posterior del proveedor no
reemplaza ese vínculo. Si no se conservó una evaluación o una línea de proyección,
la pantalla lo indica y no presenta un registro actual como si hubiera sustentado
la adjudicación.

Las fichas actuales se consultan mediante sus enlaces, mientras que los nombres,
contactos y valores de la orden permanecen en sus copias. Las revisiones históricas
de órdenes permiten consultar lo guardado antes de cada cambio.

## Verificación técnica

Veintidós pruebas nuevas comprueban creación completa y por línea, copia histórica,
impuestos y redondeo conservados, pagos contractuales, idempotencia, cambios,
revisión esperada, anulación coordinada, reversión de auditoría, permisos, CSRF y
trazabilidad real hasta FR14/proyección. La prueba PostgreSQL de aprobación
simultánea ahora comprueba también dos solicitudes concurrentes de creación de
órdenes con un único resultado. Los resultados están en [avances](avances.md).

B17 incorpora descuentos, retenciones y políticas de redondeo; consulte la
[guía de importes](importes_ordenes.md).

Aprobación/emisión, PDF directo, recepción y seguimiento completados técnicamente:
[guía de los flujos B18–B27](aprobacion_recepcion_seguimientos.md).
La preparación de Ubuntu está en [despliegue](despliegue.md).
