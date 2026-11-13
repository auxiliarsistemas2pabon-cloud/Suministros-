# Documentos exigidos y vigencias · B3

## Configuración D-05

En **Configuración → Catálogos de proveedores → Documentos exigidos** cree relaciones
de categoría y tipo de documento. Puede indicar requisito respaldado y obligatoriedad,
editar o desactivar con motivo. Un requisito debe tener peso para la categoría elegida.
Se permiten varios requisitos por tipo, sin repetir la misma combinación.

La migración deja la lista **vacía**: no hay obligaciones oficiales cargadas ni datos
reales de la clínica. La relación opcional a requisito pertenece a su versión de matriz;
al crear otra versión se deben revisar sus asociaciones. No se trasladan exigencias
oficiales sin decisión administrativa. La obligatoriedad indica el catálogo aprobado
por administración; no introduce un bloqueo automático de faltantes.

## Tableros y fechas

La ficha muestra las exigencias generales y las de la matriz aplicable hoy. La
evaluación usa su categoría y versión guardadas y su fecha de evaluación. Las fechas
por defecto provienen de `timezone.localdate()` en America/Bogota; el servicio acepta
una referencia fija para consultas reproducibles.

- **Faltante:** no hay documento expedido a la fecha de referencia, o falta una fecha
  de vencimiento que el tipo exige. Un documento expedido después no se presenta vigente.
- **Vencido:** la fecha de vencimiento es anterior a la referencia.
- **Próximo a vencer:** vence entre la referencia y el límite de alerta, inclusive.
- **Vigente:** vence después del plazo, o su tipo no requiere vencimiento y no tiene fecha.

El plazo usa el parámetro general (30 días por defecto) o el particular del tipo.
Para cada tipo se utiliza el documento más reciente expedido a la referencia.
Rojo se reserva a vencidos/faltantes; los próximos se muestran en azul claro.

El tablero consulta el catálogo y los registros documentales **actuales**, con estados
calculados a la fecha indicada. No constituye una foto histórica del catálogo completo.
Las respuestas guardan aparte el control y evidencia usados al responder.

## Responder Sí con evidencia

El selector identifica cada documento y su estado a la fecha de la evaluación.
Si hay tipos asociados al requisito, el documento seleccionado debe ser de uno de ellos
y siempre debe pertenecer al proveedor evaluado. La evidencia se clasifica por sí misma:
un documento antiguo vencido no se presenta vigente porque exista una renovación.

`evaluacion.bloquear_si_documento_vencido` es editable en Configuración → Parámetros:

- **No (por defecto):** permite Sí con advertencia si la evidencia está vencida,
  no estaba expedida o carece del vencimiento obligatorio.
- **Sí:** rechaza guardar Sí en esas condiciones. También rechaza copiar esas
  respuestas a otro borrador; se puede crear una copia sin respuestas y corregirla.

Un faltante sin documento seleccionado genera advertencia cuando el requisito tiene
documentos asociados; no se inventa una regla de bloqueo para obligaciones D-05 aún
pendientes de aprobación. Un PDF adicional sin fechas no se considera automáticamente
evidencia documental vigente. Las reglas se aplican al guardar nuevas respuestas;
no invalidan retroactivamente respuestas históricas ya guardadas o finalizadas.

Cada respuesta conserva referencia, estado de evidencia, plazo, modo de bloqueo,
exigencias aplicadas y advertencias. Las finalizadas muestran ese control sin alterarlo
cuando se renuevan documentos o se cambian parámetros. Para respuestas anteriores a B3,
se usan las fechas conservadas con el plazo general actual y se muestra esa limitación.

## Vencimientos y permisos

**Proveedores → Vencimientos** permite combinar NIT/nombre, categoría, tipo y estado
para consultar vencidos y próximos de proveedores no inactivos. La ficha y la evaluación
muestran además los faltantes de sus exigencias.

Catálogos, tableros y filtros internos requieren administrador o desarrollador. La
configuración queda auditada con motivo; las respuestas conservan su auditoría anterior/nueva.
No cambian las reglas de acceso a PDF privados.

El [vínculo documental de elegibles](vinculo_documental_elegibles.md) reutiliza estos
estados en B7, con reglas de cierre propias y conservación de una foto documental.
