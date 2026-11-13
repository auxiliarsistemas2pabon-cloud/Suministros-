# Comparativo y decisión de cotización · B13

Desde una cotización abra **Comparativo y decisión**. Administración y
Desarrolladores pueden consultar, proponer, exportar y anular con motivo. Aprobar
requiere además uno de los roles fijados en la propuesta.

## Comparación homogénea

Las filas son las especificaciones y las columnas son las ofertas. Cada celda
muestra precio unitario, subtotal, impuesto, porcentaje y total guardados. No se
recalculan ofertas con las tarifas o redondeos actuales del catálogo.

El menor costo por línea se determina por el **total con impuestos** para la
cantidad de esa especificación. Se resalta en azul claro `#dbeafe`, incluidos
todos los empates. Al pie se muestran los totales por oferente y el menor total
de oferta completa. Esta base permite comparar tarifas diferentes de forma homogénea.

El resumen incluye las verificaciones B11, su obligatoriedad, estado confirmado,
responsable, fecha y necesidad de reconfirmación. Cuando la cotización proviene
de una lista de elegibles, presenta puntaje, máximo y puesto del cierre histórico
exacto usado en B9. No sustituye ese puntaje por una evaluación posterior.

## Proponer una adjudicación

La modalidad inicial es **Oferta completa**, elegida por el usuario. Ambas opciones
están disponibles en cada propuesta:

- **Oferta completa:** un oferente recibe todas las especificaciones. Se compara
  su total con el menor total de oferta completa.
- **Por línea:** cada especificación se adjudica una vez a un oferente. Se compara
  el total de cada línea seleccionada con el menor disponible para esa línea.

Siempre se exige recomendación y motivo de registro. Si se elige un costo mayor,
se exige además una justificación de elección. Los empates de costo no generan
esa exigencia. No se admiten líneas omitidas, repetidas ni ofertas de otra cotización.

Antes de guardar se valida B12: una sola oferta requiere el caso de proveedor
único confirmado, causal, justificación y evidencia según las reglas vigentes.
Un caso marcado con varias ofertas requiere revisión. No se permite decidir sin ofertas.

Los controles activos y obligatorios de B11 en No, Pendiente o de una revisión
anterior generan alerta. El modo provisional **advertir** exige justificación
para seleccionar esos oferentes; **bloquear** impide proponerlos. Se revisan solo
los oferentes adjudicados. N/A no genera alerta. La clínica debe aprobar estas reglas.

Abrir el comparativo no registra decisiones. La propuesta firma la comparación
mostrada: si cambió mientras se revisaba, hay que recargar y revisar otra vez.

## Aprobaciones y decisión final

Registrar la propuesta deja la cotización **En comparación**. Desde el detalle
de la decisión seleccione **Aprobar esta propuesta**, con motivo. Por defecto se
requiere una aprobación de un administrador. El proponente puede aprobar si su
rol está habilitado; no se impone separación de funciones no acordada.

Se pueden exigir N aprobaciones. Cada usuario aprueba una vez y conserva su
usuario, fecha y motivo. La regla de cantidad y roles queda fijada en la propuesta;
cambios posteriores a esos parámetros solo afectan propuestas nuevas. El usuario
debe estar activo y mantener un rol habilitado al aprobar.

Antes de cada aprobación se comprueba que ofertas, verificaciones, obligatoriedad,
caso de proveedor único y reglas B12 sigan correspondiendo a la foto propuesta.
Si cambian, debe anular y registrar una propuesta nueva: las firmas anteriores
se conservan en el historial y no se trasladan a la nueva decisión.

La última aprobación requerida registra quién decidió y la fecha/hora, y deja la
cotización **Decidida**. Sus ofertas, verificaciones y caso de proveedor único
quedan en solo lectura. Dos aprobaciones simultáneas se serializan mediante el
bloqueo de la cotización; no generan dos decisiones finales.

## Cambios e historial

Para corregir una propuesta o una cotización decidida, use **Anular con motivo**.
Se conservan la selección, comparación, recomendación, evidencias referenciadas,
reglas, firmas y metadatos de decisión/anulación. La cotización vuelve a En comparación.
Registre otra propuesta tras hacer los cambios; nunca edite la decisión histórica.

Mientras una propuesta esté pendiente pueden actualizarse ofertas y verificaciones
desde sus pantallas. Esto impide seguir aprobando la propuesta anterior y exige
anularla y proponer otra. El comparativo de una propuesta existente muestra su foto
conservada; el comparativo vuelve a los datos actuales cuando ya no hay decisión vigente.

Los importes y las identidades históricas se leen de la foto guardada en
`DecisionCotizacion.contenido`; las relaciones a oferta/precio identifican el
origen, que puede cambiar tras una anulación. Las órdenes futuras deben usar esa
foto aprobada y no reinterpretar precios actuales.

## Parámetros y Excel

En **Configuración → Parámetros** puede administrar:

| Parámetro | Inicial | Alternativas |
| --- | --- | --- |
| `cotizacion.modalidad_adjudicacion` | completa | lineas |
| `cotizacion.aprobaciones_requeridas` | 1 | Entero desde 1 |
| `cotizacion.roles_aprobadores` | administrador | administrador, desarrollador o ambos |
| `cotizacion.control_verificaciones` | advertir | bloquear |

Cantidad de firmas, roles y control de verificaciones son provisionales, pendientes
de aprobación de la clínica. El valor inicial de modalidad respeta la elección del usuario.

**Exportar a Excel** incluye comparativo, verificaciones y elegibles de origen.
Si existe una propuesta, exporta su foto y decisión; desde cada decisión puede
exportar también el registro histórico después de anular y editar ofertas. Incluye
la selección y aprobaciones, con usuario y fecha. Los menores costos conservan el
azul claro y los textos que parecen fórmulas se escriben como texto.

## Verificación técnica

Veintinueve pruebas nuevas comprueban datos fijos y empates con impuestos, ambas
modalidades, justificaciones, N firmas, cambios entre firmas, B11/B12, anulación,
reversión ante fallos de auditoría, historial, Excel, permisos, CSRF y una aprobación
simultánea exclusiva de PostgreSQL. Los resultados se registran en [avances](avances.md).

B14 añade [contrato y pólizas](contratos_polizas.md). Si la cotización requiere
contrato, debe completar sus campos obligatorios antes de la primera aprobación.
Cada firma conserva la foto contractual y los datos quedan protegidos desde la primera.

B15 permite [crear órdenes en borrador](ordenes_compra.md) por proveedor adjudicado.
Al anular una decisión se anulan también sus órdenes en borrador, con historial.
Si alguna avanzó del borrador, debe resolver su anulación antes de invalidar la decisión.

B16 añade el [motor de consecutivos al emitir](consecutivos_ordenes.md), con reserva
transaccional y anulación que conserva número e historial.

Siguiente etapa: **B17, cálculo configurable de importes de la orden**.
