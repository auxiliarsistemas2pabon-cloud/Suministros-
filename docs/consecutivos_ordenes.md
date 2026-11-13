# Consecutivo y validez de órdenes · B16

Los borradores se crean sin número oficial y no consumen contador. El consecutivo
se reserva al emitir, en la misma transacción que registra estado, responsable,
fecha, reglas aplicadas y revisión histórica.

## Parámetros D-12 y D-13

En **Configuración → Parámetros** puede ajustar los siguientes valores provisionales,
pendientes de aprobación de la clínica:

| Parámetro | Inicial | Comportamiento |
| --- | --- | --- |
| `orden.prefijo_consecutivo` | OC | Prefijo normalizado a mayúsculas, hasta 20 caracteres. |
| `orden.incluir_anio_consecutivo` | Sí | Año de emisión en Bogotá. |
| `orden.longitud_consecutivo` | 4 | Mínimo de dígitos, completado con ceros. |
| `orden.reinicio_anual_consecutivo` | No | Contador global; Sí usa uno por año. |
| `orden.etiqueta_fecha_validez` | Validez / vencimiento | Nombre de la fecha opcional del borrador. |

El formato inicial es `OC-2026-0001`. Sin año y con prefijo SUM y longitud 6,
el formato sería `SUM-000001`. Se admiten letras, números, guiones y guiones bajos
en el prefijo; la longitud mínima admite 1 a 20 dígitos.

La longitud no trunca el contador: después de `9999` sigue `10000`. El año se toma
del instante de emisión convertido a Bogotá, independientemente del año de elaboración.
Si se activa reinicio anual debe incluirse el año para evitar ambigüedad.

Cambiar parámetros no renumera documentos existentes. Los números y el formato
aplicado quedan conservados incluso después de anular la orden.

## Contadores y concurrencia

El modo global utiliza el contador `global`; el anual utiliza claves como
`anio:2026`. Los contadores nunca se borran ni retroceden.

Antes de reservar se bloquean cotización, orden, parámetros y contador. Una
restricción única protege el texto del consecutivo y otra protege número/serie.
Los datos de numeración deben guardarse completos, con actor y fecha de emisión.

En emisión normal los números avanzan de uno en uno. Si falla validación, auditoría
o guardado, se revierten contador, orden y revisión: no se confirma una reserva huérfana.
Las emisiones simultáneas de cotizaciones distintas comparten la misma protección.
Repetir la emisión de una misma orden se rechaza sin consumir otro número.

Al cambiar entre modos global/anual se consideran también los números históricos
para no colisionar. En modo global se continúa desde el mayor número usado; en
modo anual se considera el mayor del año y su contador. Se comprueba además el
texto final frente a todos los documentos, incluidas las anulaciones, para evitar
reutilización ante cambios de formato.

## Fecha opcional y anulación

La creación y edición de borradores incluyen la fecha opcional con la etiqueta
configurada. Puede dejarla vacía; si se informa, no puede ser anterior a la
elaboración. No se interpreta automáticamente como entrega, caducidad contractual
u otro plazo cuya definición clínica aún está pendiente.

Los borradores muestran la etiqueta actual. Al emitir se conserva la etiqueta
usada junto con la fecha, para no reinterpretar documentos anteriores al cambiar
el parámetro.

Desde el detalle puede **Anular con motivo** una orden en borrador, En aprobación
o Emitida sin recepción. Se conservan número, fecha de emisión, importes y origen;
se registran responsable, fecha, motivo y revisión de la anulación. No se devuelve
el número al contador ni se permite reactivar la orden.

Las órdenes con recepción o cierre requieren el flujo posterior correspondiente.
Si se anula una decisión, los borradores B15 asociados también conservan los
metadatos de su anulación. Una orden ya anulada permanece consultable.

## Integración con emisión B18

El motor está en
`compras.numeracion_ordenes.numerar_al_emitir(orden, actor=..., motivo=...)`.
Requiere una orden En aprobación, todavía sin número, y origen aprobado/decidido.
Admite revisión esperada para detectar una confirmación atrasada.

**La emisión desde la interfaz y la validación de aprobaciones de la orden se
integrarán en B18.** No hay botón que emita directamente un borrador en esta etapa.
B18 debe comprobar sus aprobaciones y llamar este motor dentro de la misma
transacción; B16 cambia a Emitida y reserva el número como una única operación.

La anulación está disponible por servicio y formulario con permisos administrativos,
motivo, revisión esperada y CSRF. No cambia las aprobaciones ni el origen de la decisión.

## Verificación técnica

Veinticuatro pruebas nuevas comprueban consecutivos normales, año de Bogotá,
formato editable, reinicio anual, cambio de modo, desbordamiento del ancho mínimo,
anulación sin reutilización, reversión de auditoría, protección de contador y
metadatos, restricciones reales de base de datos, validez opcional, permisos y CSRF.
Dos de ellas ejecutan emisiones simultáneas en PostgreSQL: órdenes de cotizaciones
distintas y doble emisión de una sola orden. Resultados en [avances](avances.md).

B17 incorpora descuentos, retenciones y políticas de redondeo; consulte la
[guía de importes](importes_ordenes.md).

Aprobación/emisión, PDF directo, recepción y seguimiento completados técnicamente:
[guía de los flujos B18–B27](aprobacion_recepcion_seguimientos.md).
La preparación de Ubuntu está en [despliegue](despliegue.md).
