# Contratos y pólizas · B14

En el detalle de una cotización, seleccione **Configurar requerimiento de contrato**
antes de proponer su decisión. El valor inicial es No. Abrir las pantallas no crea
contratos ni pólizas; los cambios exigen guardar con motivo y quedan en bitácora.

## Compra con contrato y sin contrato

Una decisión que no requiere contrato se aprueba sin pedir datos contractuales ni
pólizas, aunque los parámetros generales los exijan para contratos.

Si requiere contrato, registre primero la propuesta B13 y abra **Contrato y pólizas
de esta decisión** desde su detalle. Hay como máximo un contrato por decisión.
Puede guardar un borrador incompleto y agregar sus pólizas, pero no puede aprobar
la decisión hasta completar los campos obligatorios configurados.

Para cambiar el requerimiento cuando ya hay una propuesta debe anularla con motivo
y registrar otra. La elección se conserva en el comparativo de cada decisión.
Las propuestas anteriores a B14 mantienen el comportamiento sin contrato.

## Datos del contrato

Puede registrar número, supervisor, cargo, inicio, fin de vigencia, forma de pago,
valor y PDF. El supervisor puede ser un usuario activo o un texto, sin mezclar ambas
opciones. Se conserva el nombre usado al guardar; cambiar el nombre del usuario no
reescribe ese registro. Ser supervisor no concede acceso administrativo ni permisos
de descarga.

Las fechas pueden quedar pendientes en borrador; si se indican ambas, el fin no
puede ser anterior al inicio. El valor es Decimal no negativo, con hasta dos decimales.
No se supone que el valor contractual sea automáticamente igual al valor adjudicado.

## Pólizas y tipos

En **Compras → Tipos de póliza** puede crear, editar y desactivar tipos, definir
su orden y sus días particulares de alerta. Se incluyen Cumplimiento, Calidad y
Responsabilidad civil como nombres editables, sin establecer amparos oficiales.

Desde el contrato puede agregar pólizas con tipo, aseguradora, número, valor
asegurado, inicio y fin de vigencia, PDF y estado activo. Guardar una póliza incompleta
permite continuar su captura; la aprobación exige los campos configurados para cada
póliza activa. Desactivar conserva el registro y sus evidencias. Una póliza inactiva
no satisface la exigencia de tener al menos una.

No se fijan porcentajes de cobertura, aseguradoras ni tipos obligatorios oficiales.
Se valida el orden de fechas y que el valor asegurado no sea negativo.

## Obligatoriedad configurable

En **Configuración → Parámetros** se administran estas reglas provisionales,
pendientes de aprobación de la clínica:

| Parámetro | Inicial | Uso |
| --- | --- | --- |
| `contrato.campos_obligatorios` | Datos del contrato obligatorios; PDF opcional | Objeto JSON con true/false por campo. |
| `poliza.campos_obligatorios` | Datos y PDF obligatorios para cada póliza activa | Objeto JSON con true/false por campo. |
| `contrato.exigir_poliza` | No | Sí exige al menos una póliza activa y completa. |

Campos conocidos del contrato:

```json
{"numero":true,"supervisor":true,"cargo":true,"fecha_inicio":true,"fecha_fin":true,"forma_pago":true,"valor":true,"pdf":false}
```

Campos conocidos de cada póliza:

```json
{"tipo":true,"aseguradora":true,"numero":true,"valor_asegurado":true,"vigencia_desde":true,"vigencia_hasta":true,"pdf":true}
```

Cada objeto debe contener todos sus campos con valores booleanos; no se aceptan
campos desconocidos, listas o textos como `"si"`. Puede cambiar cualquier campo
a false. El supervisor obligatorio admite usuario o texto; un valor monetario cero
se considera informado. Tener alguna póliza se configura por separado.

## Aprobaciones e historial

Antes de cada aprobación B13 se validan el contrato y sus pólizas según las reglas
vigentes. Cada firma conserva una foto con datos, revisiones, pólizas, referencias
a PDF y obligatoriedad aplicable.

La primera firma protege el contrato y sus pólizas, aunque todavía falten aprobaciones
para decidir. Si cambia la obligatoriedad entre firmas, se exige revisar y registrar
una propuesta nueva, conservando las firmas anteriores. La decisión final no se
completa sin la validación contractual.

Para corregir datos después de una firma o de la decisión final, anule la decisión
con motivo y registre otra propuesta con su propio contrato. El contrato de la
decisión anterior permanece de solo lectura. No se copian contratos automáticamente.

Cada guardado del contrato o de cualquier póliza incrementa la revisión contractual
y conserva una foto de todo el conjunto con actor, fecha y motivo. La revisión
esperada impide sobrescribir cambios realizados mientras el formulario estaba abierto.

## PDF privados

Los PDF admiten hasta 10 MB y usan la validación existente de extensión y cabecera.
Se guardan con UUID en almacenamiento privado. Las descargas requieren Administración
o Desarrollador y comprueban cotización, decisión y adjunto. Quedan auditadas, con
`nosniff` y sin caché.

Reemplazar o retirar el PDF y desactivar una póliza conserva las evidencias anteriores,
accesibles desde las revisiones. Las revisiones y adjuntos históricos son inmutables.
Si falla el guardado o la auditoría, se revierte la operación y se elimina únicamente
el PDF nuevo sin confirmar. Las cargas rechazan transacciones externas.

## Alertas de vigencia

En **Compras → Vigencias de pólizas** puede filtrar por fecha y estado. El tablero
general incluye pólizas activas de decisiones pendientes o aprobadas y excluye las
anuladas; estas siguen consultables desde su contrato histórico.

Se reutiliza `proveedores.documental.clasificar` de B3:

- Sin inicio, inicio posterior a la consulta o sin vencimiento: sin vigencia acreditada.
- Vencimiento anterior a la consulta: vencida.
- Vencimiento entre la consulta y el umbral de alerta, ambos inclusive: próxima a vencer.
- Vencimiento posterior al umbral: vigente.

El día del vencimiento aún está vigente, con alerta. El umbral general proviene de
`proveedor.dias_alerta_vencimiento`; cada tipo puede definir días particulares.
Vacío usa el general y 0 avisa el mismo día del vencimiento. Las alertas informan
la vigencia a fecha y no introducen reglas adicionales de bloqueo de la decisión.

## Verificación técnica

Veintiocho pruebas nuevas cubren compras con/sin contrato, obligatoriedad por campo,
supervisor, vigencias, alertas y filtros, archivos privados, permisos, CSRF, historial,
revisiones concurrentes y reversión de PDF/auditoría. La prueba PostgreSQL de firmas
simultáneas B13 ahora usa un contrato completo. Los resultados se registran en
[avances](avances.md).

B15 incorpora [órdenes de compra](ordenes_compra.md) con copia de las condiciones
de pago de la foto contractual aprobada, sin reinterpretar datos actuales.

Siguiente etapa: **B17, cálculo configurable de importes de la orden**.
