# Verificaciones de ofertas · B11

Desde una cotización o una oferta abra **Verificaciones**. La matriz presenta
los oferentes y los controles, el estado confirmado, responsable, fecha y acceso
al historial. Solo Administración y Desarrolladores pueden consultar o modificar
estos registros y descargar sus evidencias.

## Catálogos y estados

En **Compras → Tipos de verificación** puede administrar tipos y estados con motivo y
bitácora. Los tipos tienen orden, obligatoriedad, origen manual/documental y
activación. Se incluyen Vigencia documental, Requisitos técnicos, Sarlaft y Sicof,
todos inicialmente opcionales: la clínica debe establecer las obligaciones reales.

Los estados iniciales son Sí, No, Pendiente y N/A. Puede cambiar sus nombres,
orden y activación o crear otros; cada uno conserva una clasificación que define
su significado para las alertas. Los registros guardan nombre y clasificación
confirmados, de modo que editar el catálogo no reescribe el historial.

La matriz alerta si un tipo activo y obligatorio está en No, Pendiente o carece
de confirmación. Los tipos desactivados con registros anteriores siguen visibles
para consulta. Esta etapa muestra alertas; no decide cotizaciones ni crea órdenes.

## Confirmación y evidencia

Cada verificación conserva fecha, usuario que confirma, observación, revisión de
la oferta y motivo de la operación. Puede adjuntar un PDF privado opcional.
Cada guardado genera una revisión inmutable con los datos y el PDF de ese momento.
Reemplazar o retirar evidencia conserva las revisiones y archivos anteriores.

Los PDF admiten hasta 10 MB y deben superar la validación de extensión y cabecera.
Se guardan con UUID en almacenamiento privado. La descarga comprueba el rol y la
pertenencia a cotización, oferta y verificación; queda auditada, sin caché y con
`nosniff`. No hay URL pública del archivo.

El guardado de evidencia utiliza una transacción durable. Si falla la validación
o la auditoría, se revierte el registro y se elimina solo el PDF nuevo sin confirmar.
Las cargas rechazan transacciones externas para impedir que una reversión posterior
deje archivos huérfanos. Las evidencias históricas no se eliminan.

Al guardar una nueva revisión de la oferta, sus verificaciones anteriores quedan
marcadas para revisión. La matriz las trata como Pendiente hasta reconfirmar,
conservando el estado original y la revisión de oferta que lo sustentaba.
Las cotizaciones decididas o anuladas permiten únicamente consulta.

## Propuesta documental

Para un tipo de origen documental seleccione la fecha de consulta. Se reutiliza
el tablero B3 y la última evaluación FR14 finalizada no anulada cuya fecha no sea
posterior a la consulta. Si no existe, se utiliza la categoría actual del proveedor.
El catálogo de exigencias es el vigente al consultar: no se reconstruye un catálogo
histórico que aún no se hubiera conservado.

| Situación a la fecha consultada | Propuesta |
| --- | --- |
| Algún documento obligatorio vencido o faltante | No |
| Alertas solo en documentos opcionales | Pendiente |
| Sin exigencias configuradas | Pendiente |
| Todos vigentes, incluidos los próximos a vencer | Sí |

Un documento con expedición posterior a la fecha consultada no acredita vigencia
en esa fecha. El día del vencimiento todavía se considera vigente, con alerta de
próximo vencimiento según B3. La lista oficial D-05 sigue pendiente de aprobación.

Abrir la propuesta no registra una verificación. Debe marcar la confirmación,
elegir el estado y guardar con motivo; si se aparta de la propuesta, debe explicar
la diferencia en la observación. La firma de la propuesta impide confirmar datos
alterados o una propuesta que cambió mientras se revisaba: debe consultarla otra vez.
La fecha documental se fija a la de la propuesta mostrada.

Se conserva la propuesta confirmada con documentos, fechas, exigencias, evaluación
y resultado. Las renovaciones posteriores no modifican esa evidencia histórica.
La matriz distingue la propuesta actual del estado que una persona confirmó.

Requisitos técnicos, Sarlaft y Sicof se registran inicialmente como revisión manual;
no se ejecutan consultas externas ni se presume cumplimiento al abrir la pantalla.

## Verificación técnica

Diecisiete pruebas en `compras/tests_verificaciones.py` cubren estados, responsable
y fecha, alertas, catálogos, revisión de oferta, evaluación y documentos a fecha,
confirmación explícita, propuestas alteradas, historial, PDF privados, reversión,
permisos y CSRF. Los resultados de ambas bases se registran en [avances](avances.md).

B12 incorpora el [caso de proveedor único](proveedor_unico_cotizacion.md), con
causal, justificación y evidencia configurable para validar antes de decidir.

B13 integra las verificaciones en el [comparativo y decisión](decision_cotizacion.md),
con advertencia justificada o bloqueo configurables para los oferentes seleccionados.

B14 añade [contratos y pólizas](contratos_polizas.md), con validación contractual
antes de aprobar una compra que los requiere.

B15 conserva en las [órdenes](ordenes_compra.md) la trazabilidad a la evaluación
documental usada, si fue confirmada en el origen.

Siguiente etapa: **B17, cálculo configurable de importes de la orden**.
