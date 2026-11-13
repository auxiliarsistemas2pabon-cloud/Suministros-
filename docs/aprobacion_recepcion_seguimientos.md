# B18–B27 · Aprobación, recepción y seguimiento

## Aprobar y emitir la orden

En **Configuración → Parámetros**, configure primero `orden.cliente_nombre` y
`orden.cliente_nit`. El valor inicial `POR CONFIGURAR` impide solicitar aprobación;
no se inventan datos de la clínica. Revise también las políticas contables B17.

Desde el detalle del borrador, indique motivo y solicite aprobación. La solicitud
conserva el contenido comercial, el cliente y las reglas aplicables. La orden queda
en aprobación y no se puede editar. Cada solicitud tiene un ciclo independiente.

La elección del usuario es **otra persona administradora distinta del elaborador**.
`orden.permitir_aprobar_propia` comienza en `false`; cualquier cambio se aplica a
solicitudes futuras. Pueden firmar administradores y desarrolladores activos.
Una persona responde una sola vez por ciclo, con comentario obligatorio.

En **Compras → Aprobación de órdenes**, configure reglas por rango de total a pagar
y categoría del proveedor. Desde es inclusivo y hasta exclusivo; la categoría vacía
aplica a todas. Si coinciden varias reglas, se exige el mayor número de firmas.
Sin regla específica se exige una. Las firmas requeridas y la categoría se conservan
al solicitar; cambiar un catálogo después no reduce una aprobación en curso.

Un rechazo devuelve la orden al borrador y conserva solicitud, firma y motivo.
Tras corregir y solicitar de nuevo, no se reutilizan firmas de ciclos anteriores.
La última aprobación suficiente emite la orden y asigna su número, todo en una
transacción. Se comprueba que el contenido siga coincidiendo con lo revisado y con
su cálculo. Una reversión no deja firma, número o seguimiento parcialmente guardados.
El bloqueo de cotización/orden serializa respuestas simultáneas.

La elección de formato es **PDF generado directamente por la aplicación**. El botón
**Descargar orden PDF · FR-GDS-21** usa la foto emitida: clínica/NIT, consecutivo,
proveedor, cotización, área, pago, fechas, ítems, importes, elaborador y aprobadores.
Incluye páginas y desglose; nombres, tarifas o parámetros posteriores no lo reescriben.
Una orden anulada se descarga con aviso de anulación y conserva el documento de origen.
La librería de generación está fijada en `requirements.txt`.

En **Registrar evidencia de envío**, conserve la fecha/hora del envío que hizo al
proveedor y un PDF opcional. No se envían correos desde esta acción. El envío no
precede a la emisión ni se fecha en el futuro. Una corrección crea otra evidencia
con referencia a la anterior; los soportes se descargan con permisos.

## Recepciones, rechazos, ajustes y devoluciones

La elección inicial es **solo administradores y desarrolladores**. El parámetro
`orden.coordinador_puede_recibir` permanece en `false`. Si se habilitara, el servicio
limita al coordinador activo al área de origen; no le permite autorizar excesos.

Solo se reciben órdenes emitidas vigentes, sin cierre. En el detalle, registre
fecha, motivo y cantidades por línea. Los PDF son opcionales, privados y de máximo
10 MB. La fecha no precede a la emisión ni se registra en el futuro.

- **Recepción:** cantidad aceptada y cantidad rechazada no negativas; lo rechazado
  se informa aparte y no reduce el pendiente de aceptación.
- **Ajuste:** referencia a una recepción de la misma orden, cantidades con signo y
  motivo. Corrige el libro sin editar el movimiento anterior. No puede dejar
  acumulados aceptados, rechazados o devueltos negativos.
- **Devolución:** indique solo cantidad devuelta positiva. Se descuenta automáticamente
  de lo aceptado y aumenta el pendiente. Ajustar una devolución exige cantidades
  aceptadas y devueltas opuestas. No se puede devolver más de lo aceptado.

Pendiente = máximo entre cero y ordenado menos aceptado neto.
El exceso se informa aparte. El estado de orden se deriva: emitida sin aceptaciones,
recibida parcial con algún saldo y recibida total sin pendientes.

`orden.permitir_exceso_recepcion` comienza en `false`. Para aumentar un exceso se
requieren ese parámetro habilitado, casilla de autorización expresa, persona
administradora y motivo. Se conserva la política aplicada en el movimiento.
Reducir un exceso con ajuste no requiere volver a autorizarlo.

## Iniciar y corregir seguimiento

**Seguimientos** enlaza con el panel FR-GDS-27. Por defecto, emitir una orden crea
su seguimiento en la misma transacción (`seguimiento.crear_al_emitir=true`). Si lo
desactiva, puede iniciarlo manualmente desde una orden emitida o un contrato aprobado.
Repetir la creación devuelve el registro existente; cada orden tiene como máximo uno.
Si ya había recepciones, ajustes o devoluciones antes de iniciar el seguimiento,
se incorporan sus eventos pendientes en la misma transacción. Conservan responsable,
fecha del movimiento, observación y referencia al PDF original. La bitácora identifica
a la persona que incorporó el historial y el motivo actual. Repetir la acción no
duplica eventos ni archivos; un fallo revierte la incorporación completa.

Los tipos iniciales editables son Contratos, Compras generales, Servicio farmacéutico
y Hemodinamia. Área, proveedor, objeto y valor se copian del origen. Para iniciar un
seguimiento contractual sin orden se exige un único proveedor adjudicado y un valor
conservado en la aprobación del contrato; si hubo reparto, use las órdenes por proveedor.

**Corregir datos con motivo** registra valor anterior/nuevo y revisión, sin cambiar
el origen, la orden o el contrato. También permite indicar comité y fecha. Los cambios
de valor del seguimiento aparecen diferenciados del valor de las órdenes en los reportes.

## Línea de tiempo, entregas y cierre de líneas

Agregue eventos con tipo, fecha del evento, nota y PDF opcional. La fecha de registro
y autor se conservan aparte. Los eventos no se editan ni se borran: una corrección
referencia al anterior, que permanece visible. No se permiten ramas de correcciones
simultáneas del mismo evento; corrija la última entrada de la cadena.

Cada recepción, ajuste o devolución genera automáticamente un evento si la orden tiene
seguimiento. El evento referencia el movimiento real y reutiliza su PDF; no crea un
segundo libro de cantidades ni otra copia del soporte. Una corrección de nota no
corrige cantidades: para eso use un ajuste de recepción.

La tabla de entregas muestra ordenado, aceptado neto, rechazado, devuelto, pendiente y
estado por línea. **Cerrar línea** conserva motivo, autor y saldo. Una línea cerrada
no admite recepciones hasta **Reabrir línea**, también con motivo. Ambas acciones
quedan en el historial. Cerrar con saldo no hace desaparecer cantidades pendientes.

## Hitos y estados operativos

No se precargan plazos SLA reales. En **Plantillas de hitos**, configure por tipo de
seguimiento un nombre, evento de referencia opcional, evento de cumplimiento y días.
Sin referencia, el plazo parte de la apertura. Con referencia, se usa la última fecha
de ese evento vigente; un evento de cumplimiento posterior satisface el hito.

Los seguimientos conservan su versión de hitos. **Actualizar hitos desde plantillas
actuales** exige motivo y crea otra versión; la anterior no se borra. Cambiar un
catálogo no modifica silenciosamente un plazo ya guardado.

Se considera vencido cuando pasa la fecha límite, no durante el propio día límite.
Los eventos fechados en el futuro permanecen visibles pero no cumplen ni activan
hitos antes de su fecha. Las correcciones sustituyen la función operativa del evento
corregido y conservan ambos en la línea de tiempo.

Prioridad provisional de derivación, pendiente de D-15:

1. Cerrado si hay cierre vigente.
2. Atrasado si hay hito vencido sin cumplimiento o pasó la entrega esperada con saldo abierto.
3. En espera de documentos si el último evento documental vigente solicita documentos.
4. Completo si todas las líneas están completas o tienen cierre justificado.
5. Parcial si hay aceptación neta con saldo; abierto en los demás casos.

La fecha esperada de entrega se registra en el borrador de la orden y se conserva al
aprobar; es distinta de la fecha opcional de validez/vencimiento. El panel muestra
contadores y próximos hitos pendientes en una ventana inicial de siete días, editable
con `seguimiento.dias_alerta`. Solo el estado atrasado se presenta en rojo.
`python manage.py seguimientos_atrasados --fecha AAAA-MM-DD` lista atrasos para una
fecha dada y no envía comunicaciones.

## Cierre y reapertura

**Cerrar seguimiento** requiere resultado activo, fecha entre apertura y hoy,
observación y responsable. Los resultados iniciales son Cumplido, Cumplido con
novedades, Incumplido y Anulado. Cierre, eventos y documentos siguen consultables.

`seguimiento.cierre_con_saldo` comienza en `bloquear`: exige cerrar con motivo las
líneas con saldo antes de cerrar el seguimiento. `advertir` permite cerrar con saldo
sin cierre de línea, dejando advertencia e identificadores pendientes en el registro.
La orden asociada pasa a cerrada cuando estaba en un estado operativo compatible.

No se admiten nuevos eventos o recepciones mientras el seguimiento esté cerrado.
`seguimiento.permitir_reapertura=false` deshabilita inicialmente la reapertura.
Habilitarla no basta por sí solo: la acción requiere administración, revisión actual
y motivo. Conserva el cierre anterior y deriva de nuevo el estado de la orden usando
el libro real. Una reapertura de seguimiento no reabre silenciosamente sus líneas.

## Reportes y búsqueda común

El panel combina año/rango de apertura, área, proveedor por NIT/nombre, categoría,
tipo, consecutivo de orden y estado derivado. Pagina resultados; Excel usa exactamente
el mismo conjunto filtrado y no solo la página actual.

La base de datos agrega número de seguimientos, suma de valores y valor de las órdenes
incluidas. Los valores del seguimiento pueden incluir correcciones justificadas o un
contrato sin orden: se muestran separados del total de órdenes. Aceptado, rechazado,
devuelto y pendiente se agregan por unidad, evitando sumar cajas con unidades distintas.
El cierre con saldo no borra esos pendientes. Los textos exportados se escriben como
texto para impedir que se interpreten como fórmulas de Excel.

El acceso inicial a seguimiento es administrativo. Si se habilita
`seguimiento.coordinador_puede_consultar`, los coordinadores solo consultan y exportan
su propia área. No pueden mutar seguimientos ni catálogos. Ese parámetro permanece
deshabilitado; no amplía la elección inicial de recepción.

**Listados** ofrece el componente común por proyecciones, proveedores, evaluaciones,
necesidades, elegibles, cotizaciones, órdenes y seguimientos, con los filtros que
corresponden a cada modelo y exportación con idéntico alcance. El listado general de
seguimientos también filtra por estado derivado y lo incluye en Excel. Los listados
principales de compras usan el mismo formulario y función. Proyecciones conserva
además su consolidado existente; el panel de seguimiento añade sus indicadores.

La barra superior busca NIT o consecutivo; admite NIT canónico, con puntos y con dígito
de verificación, usando la misma normalización de las fichas. Muestra hasta 25 resultados
por módulo; puede refinar y exportar en los listados. Los permisos se aplican antes de
los filtros y una URL manipulada no amplía el área autorizada.

## Verificación y límites

Se prueban firmas suficientes y distintas, rechazo por ciclo, reglas congeladas,
PDF real, soportes privados, recepciones y excesos, ajustes, devoluciones, conservación
del origen, eventos y correcciones, hitos con fechas fijas, cierre/reapertura, filtros,
agregados y coincidencia con Excel. PostgreSQL incluye respuestas concurrentes sin
duplicar firma ni número. Resultados completos en [avances](avances.md).

La revisión transversal B26 conserva las protecciones de usuarios desarrolladores,
las descargas propias del portal, la reutilización/limpieza transaccional de PDF y
la configuración de seguridad. La comprobación de referencias incluye ahora soportes
de envíos, recepciones y eventos para no retirar un archivo compartido.

La preparación de Ubuntu, respaldos y restauración está en [despliegue](despliegue.md).
Las decisiones de negocio de la clínica y el ensayo en la VM siguen pendientes de
sus responsables; completar las etapas técnicas no las sustituye.
