# Historial, anulación y copia de evaluaciones · B2

En la ficha del proveedor, **Historial de evaluaciones FR-GDS-14** muestra las diez
evaluaciones más recientes con fecha, versión, evaluador, porcentaje, calificación
y estado. «Consultar todo el historial» abre el listado paginado con enlaces al
detalle. El orden es fecha de evaluación descendente y, a igualdad, identificador.

## Evaluación vigente

La vigente es la última **finalizada y no anulada**, ordenada por fecha de
finalización e identificador. Crear un borrador o una copia no la cambia. Al
finalizar otra evaluación, esta pasa a ser vigente; si se anula, vuelve a ser
vigente la finalizada anterior, o ninguna si no queda otra.

La propiedad `Proveedor.evaluacion_vigente` ofrece esta regla a los módulos futuros.
No significa aprobación de las reglas D-06 ni certificación de vigencia documental;
estas condiciones se tratan aparte. Una evaluación puede utilizar reglas provisionales.

## Anular

Desde el detalle seleccione «Anular con motivo». Solo admite POST con CSRF y exige
motivo no vacío. Se puede anular un borrador o una finalizada; no se repite una
anulación. Se conservan responsable, fecha, motivo, resultados y evidencias.

Una finalizada mantiene exactamente su foto de resultados y la información de
finalización. Un borrador anulado conserva una foto de su cálculo parcial al anularlo,
incluido «No calculable» si corresponde. La anulación no borra PDF ni respuestas.
Ambos estados quedan en solo lectura tanto en las vistas como en los servicios.

## Copiar

«Copiar a un borrador nuevo» conserva proveedor, categoría, nombre de categoría,
versión y fecha de evaluación del origen, incluso si su matriz ya fue retirada.
La copia conserva un vínculo al origen y un identificador independiente.
Para usar otra fecha, categoría o matriz vigente, cree una evaluación nueva desde
la ficha en lugar de copiar una anterior.

Puede copiar respuestas y evidencias actuales o comenzar sin respuestas. Al copiar,
las respuestas nuevas registran al actor de la copia y el motivo en bitácora; el
origen conserva sus responsables y fechas. Los PDF se referencian mediante adjuntos
propios de la copia, **sin duplicarlos en disco**. Las fotos documentales se conservan.
El historial de adjuntos antiguos no usados por las respuestas actuales queda en
la evaluación de origen.

No se copia el resultado final ni la información de anulación/finalización. El
borrador nuevo calcula con las reglas D-06 actuales y guardará su propia foto si
se finaliza. Corregir la copia no cambia respuestas ni resultados del origen.

## Seguridad y trazabilidad

Solo administradores y desarrolladores acceden al historial, copias y anulación.
Coordinadores y proveedores reciben 403. Las operaciones bloquean la evaluación
de origen en una transacción y registran actor, fecha, acción y motivo en bitácora;
los fallos revierten todos los registros nuevos o la anulación.

**B3 ya está disponible:** [documentos exigidos por categoría y alertas vinculadas a requisitos](control_documental.md).
