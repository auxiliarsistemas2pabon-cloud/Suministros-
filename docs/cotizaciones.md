# Encabezado y líneas de cotización · FR-GDS-28 · B9

Administradores y desarrolladores pueden registrar cotizaciones desde **Compras →
Nueva cotización** o desde **Iniciar cotización** en una lista de elegibles cerrada.
Cada cotización pertenece a una necesidad abierta y a su área. El usuario que la
registra queda como responsable; inicia en borrador.

## Registro manual

Puede consultar primero una necesidad para precargar sus líneas. Complete objeto,
fecha y tipo, y registre al menos una especificación con descripción, unidad del
catálogo y cantidad positiva con hasta tres decimales. La especificación técnica
admite texto adicional. Puede seleccionar proveedores activos registrados o dejar
las invitaciones vacías al crear el encabezado.

Las líneas pueden vincularse opcionalmente a un origen de la misma necesidad.
Se conserva la descripción de la unidad y una foto del origen. No se aceptan líneas
de otras necesidades ni se convierten unidades automáticamente. Cuando no hay una
correspondencia clara, debe indicar unidad y cantidad expresamente.

## Desde una lista cerrada

**Iniciar cotización** abre el formulario con objeto y líneas conservados al cerrar
la lista. Solo los participantes con cantidad autorizada positiva se copian como
invitados, con NIT, razón social y cantidad de origen. La invitación no es una oferta
ni incorpora precios.

La cotización conserva la lista y su cierre histórico exacto. Si la necesidad era
manual, se propone el objeto y cantidad base, y debe elegir una unidad del catálogo.
Si una unidad está inactiva, no se selecciona automáticamente como válida.

La precarga no crea registros: debe enviar **Crear cotización en borrador**. El
servidor comprueba que la lista siga cerrada y corresponda a la necesidad. Una
revisión firmada detecta si cambió el cierre desde que abrió el formulario.
No se pueden añadir invitados ajenos a los elegidos mediante un POST manipulado.

Al guardar se crea la asociación real `Cotizacion.lista_elegibles`. La lista muestra
**Con cotización** y quedan bloqueadas su reapertura y anulación. La creación
bloquea necesidad y lista en el mismo orden que las transiciones B8.

## Límites D-10

Configure en **Configuración → Parámetros**:

| Parámetro | Inicial | Significado de 0 |
| --- | --- | --- |
| `cotizacion.max_oferentes` | 3 | Sin límite de negocio de invitados |
| `cotizacion.max_lineas` | 10 | Sin límite de negocio de líneas |

Los valores iniciales están pendientes de aprobación de la clínica. Se admiten
enteros no negativos y siempre se exige al menos una línea. Los límites se
comprueban en servidor y se conservan como parámetros aplicados en cada cotización.

Una precarga que excede el límite no se trunca ni guarda parcialmente. Revise el
parámetro o el origen. La pantalla permite agregar especificaciones y marcar
Eliminar para omitir filas; los proveedores del cierre se mantienen como fueron elegidos.

## Tipos y consecutivo

**Compras → Tipos de cotización** permite crear, editar y desactivar tipos con
motivo y bitácora. Se incluyen Compra, Servicio y Contrato como tipos iniciales
editables, sin pretender definir una clasificación oficial. Los nombres no se
repiten sin distinguir mayúsculas y desactivar conserva las cotizaciones anteriores.

El consecutivo interno tiene forma `COT-2031-000001`: año de la fecha de la cotización
y número global ascendente. No reinicia al cambiar de año. Se asigna al guardar,
con bloqueo transaccional y unicidad en base de datos. Un fallo de validación o
auditoría revierte encabezado, líneas, invitados y número. No define la numeración
oficial de órdenes futuras.

## Consulta y trazabilidad

**Cotizaciones** muestra consecutivo, objeto, fecha, área, responsable, tipo y estado.
El detalle presenta especificaciones e invitados y enlaces a necesidad, lista,
cierre histórico y proyección de las líneas vinculadas. Necesidad y lista muestran
a su vez sus cotizaciones asociadas.

Cada alta, cambio de tipos, asignación de consecutivo, línea e invitación queda en
bitácora con usuario, fecha y motivo. Los modelos se consultan en solo lectura en
el administrador técnico. B10 añade la [captura de ofertas](ofertas.md), con precios,
tarifas, PDF privados e historial; no se crean órdenes automáticamente.

Dieciséis pruebas nuevas en `compras/tests_cotizaciones.py` cubren registro manual
y desde lista, límites exactos y valor 0, cantidades inválidas, tipos/unidades
inactivos, unicidad de NIT, consecutivos y reversión, revisión de origen, navegación,
permisos y CSRF. La reapertura/anulación se prueba ahora con cotización real.

B11 añade la [matriz de verificaciones por oferente](verificaciones_ofertas.md),
con tipos y estados configurables, propuesta documental que exige confirmación
y evidencia privada con historial.

B12 añade el [caso de proveedor único](proveedor_unico_cotizacion.md) y su validación
previa a la decisión, con causal, justificación y PDF según parámetros.

B13 añade [comparativo, adjudicación y aprobaciones](decision_cotizacion.md), con
decisiones históricas y exportación Excel. La modalidad inicial es oferta completa,
según la elección del usuario, y puede cambiarse a adjudicación por línea.

B14 permite indicar [si la compra requiere contrato](contratos_polizas.md) antes de
proponer la decisión y completar contrato y pólizas con obligatoriedad configurable.

B15 permite [generar órdenes desde la decisión aprobada](ordenes_compra.md), con
copia independiente y vínculos a cotización, lista, evaluación y proyección de origen.

Siguiente etapa: **B17, cálculo configurable de importes de la orden**.
