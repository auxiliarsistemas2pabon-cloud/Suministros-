# Vínculo documental de elegibles con FR-GDS-14 · B7

Desde una lista abra **Evaluación FR14 y estado documental**. Solo Administrador
y Desarrollador pueden consultar, justificar o exportar este control.

## Evaluación y documentos de cada participante

El borrador muestra la evaluación vigente del proveedor definida en FR14: la
última finalizada no anulada, ordenada por fecha de finalización. Los borradores
no sustituyen una evaluación finalizada. Se muestran calificación, fecha,
categoría, versión, límite por antigüedad y enlace a la evaluación.

La referencia predeterminada es la fecha actual de Bogotá. La antigüedad se cuenta
desde la fecha de evaluación en meses calendario, no como meses de treinta días.
El aniversario todavía es válido y el día siguiente se considera antiguo. Si no
existe el día en el mes de destino, se usa su último día: 29/02 + doce meses termina
el 28/02 del año siguiente. Una evaluación con fecha futura no se presenta vigente.

El tablero documental reutiliza B3 con la categoría y versión guardadas en la
evaluación, y la fecha de revisión. Si no hay evaluación, usa la categoría actual
del proveedor y las exigencias aplicables. Se identifican documento, requisito,
obligatoriedad, estado, fechas y referencia del documento que sustenta cada fila.
Solo se consideran documentos expedidos a la fecha de referencia.

Se muestran alertas de evaluación ausente/antigua/futura y documentos vencidos o
faltantes. Los próximos a vencer son informativos. Un catálogo de exigencias vacío
no acredita una lista documental oficial completa: D-05 continúa pendiente.

## Parámetros provisionales

Configure en **Configuración → Parámetros**:

- `elegibles.control_documental`: `advertir`, inicialmente, o `bloquear`.
- `elegibles.antiguedad_evaluacion_meses`: entero positivo, inicialmente 12.

Ambas decisiones están pendientes de aprobación de la clínica. Son controles de
FR-GDS-20 y no modifican el parámetro D-05 usado para responder Sí en FR14.

Solo se aplican controles de cierre a participantes con cantidad autorizada mayor
que cero. Las alertas de otros participantes permanecen visibles.

| Condición de un elegido | Advertir | Bloquear |
| --- | --- | --- |
| Sin FR14 finalizada vigente, antigua o con fecha futura | Requiere justificación | Impide cerrar |
| Documento obligatorio vencido | Requiere justificación | Impide cerrar |
| Documento faltante u opcional vencido | Requiere justificación | Requiere justificación |
| Documento próximo a vencer | Informativo | Informativo |

El alcance de bloqueo corresponde al prompt B7: evaluación vigente y documentos
obligatorios vencidos. Los faltantes se advierten y justifican; no se inventa una
prohibición adicional mientras se aprueba D-05. Una justificación no permite
omitir las condiciones que el modo `bloquear` impide.

## Justificación y revisión

En el borrador indique la justificación para continuar con advertencias y el motivo
de su registro. **Comprobar revisión y guardar justificación** valida el control
actual y conserva el texto con bitácora. No cierra la lista ni fija todavía la foto.

Los parámetros, evaluaciones y documentos se comprobarán nuevamente al cerrar.
Una justificación guardada no evita un bloqueo si después cambia el modo o aparece
una condición bloqueante. La validación documental complementa la calificación,
cantidades y decisiones de B5–B6; por sí sola no autoriza el cierre.

## Foto documental de cierre

B8 integra el control documental y `conservar_al_cerrar` en la acción **Cerrar lista**.
El flujo valida B5/B6 y B7, cambia el estado y conserva la
foto dentro de una única transacción. Un error revierte también el cambio de estado.
Cada cierre completo se archiva; reabrir libera la foto activa sin borrar el archivo.

Al conservar se guarda, por participante activo:

- Referencia fija a la evaluación FR14 utilizada, si existe.
- Calificación, fecha, categoría, versión y límite por antigüedad de esa evaluación.
- Exigencias y documentos usados, con sus identificadores, estados, obligatoriedad,
  fechas, plazos de alerta y advertencias/informativas.

La lista guarda además fecha de referencia, modo, antigüedad máxima, justificación,
usuario y momento de captura. El guardado exige rol administrativo, motivo, estado
cerrado y ausencia de una foto anterior; el control y sus registros de bitácora son
transaccionales. No se copian PDF ni se publican rutas de archivos privados.

Las listas cerradas/anuladas se consultan con los datos conservados. Crear o anular
otra evaluación, renovar documentos o modificar parámetros no cambia la referencia
ni el estado histórico. Una lista anterior sin foto se identifica expresamente y
no se reconstruye con datos actuales.

## Excel y pruebas

La exportación de B6 incorpora **Estado documental**, con evaluación, calificación,
alertas y documentos. Identifica si es consulta actual o foto histórica y conserva
los controles de acceso y tratamiento seguro de textos del libro existente.

Quince pruebas nuevas en `compras/tests_documental.py` cubren selección de FR14,
antigüedad y meses calendario, fechas futuras, estados documentales, ambos modos,
elegidos/no elegidos, justificación, foto histórica, atomicidad, permisos, CSRF y Excel.
El cierre se simula dentro de una transacción en las pruebas de conservación.

La [guía de cierres](cierres_elegibles.md) describe B8 y sus transiciones.
Siguiente etapa: **B9, encabezado y líneas de cotización**.
