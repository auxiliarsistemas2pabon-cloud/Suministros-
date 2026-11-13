# Avances del proyecto

## 2026-11-12 · Revisión de integración posterior a B28

- Se reprodujeron con pruebas tres fallos de integración y se corrigieron:
  el listado general de seguimientos omitía su estado derivado, los seguimientos
  iniciados después de recibir no incorporaban los movimientos anteriores en la
  línea de tiempo, y un paquete de restauración sin base podía superar la validación.
- El filtro común ofrece estados operativos válidos, aplica el mismo conjunto a
  pantalla/Excel e incluye el estado derivado en la exportación. Un estado desconocido
  se rechaza y no amplía los resultados.
- Iniciar o consultar idempotentemente la creación de un seguimiento abierto incorpora
  eventos de recepciones, devoluciones y ajustes pendientes. Conserva autor, fecha y
  observación originales, comparte el mismo PDF y registra quién incorporó el
  historial y su motivo. La incorporación completa se revierte si falla la auditoría;
  no se recalculan ni duplican cantidades.
- Antes de restaurar se exigen manifiesto válido, motor/base concordantes, archivo de
  base presente, SHA-256 válido y cabecera SQLite/PostgreSQL custom. SQLite se abre
  en solo lectura y se comprueba su integridad antes de abrir la base de destino.
  Los ensayos de rechazo conservan expresamente los datos anteriores del destino.
- Se añadió un recorrido completo por formularios con cambio de actor: solicitud,
  rechazo de firma propia, aprobación por otra cuenta, PDF, recepción parcial,
  devolución, revisión obsoleta rechazada, exportación de saldos, recepción total,
  cierre e intento de evento posterior al cierre. Solo usa datos ficticios aislados.

### Verificación

- **Seis pruebas nuevas**; los tres fallos originales se observaron antes de corregirlos.
- SQLite: **866 pruebas sin fallos**, con seis exclusivas de PostgreSQL omitidas.
- PostgreSQL 18.6: **866 pruebas correctas**, incluidas concurrencia y restauración
  en bases ficticias aisladas. Instancia temporal detenida al finalizar; sin cambios
  en la base PostgreSQL nativa.
- `check`, `makemigrations --check --dry-run` y `migrate --check` correctos; no se
  necesitan migraciones nuevas ni se restauró la base local.
- Verificación HTTP de ingreso, panel, filtro por estado y Excel con ambos roles
  administrativos; filtros inválidos responden 400. Las dos cuentas conservan sus
  contraseñas. App activa en `http://127.0.0.1:8001/ingresar/`.
- Respaldo previo compatible con la validación reforzada e integridad SQLite comprobados.
  No se modificó `.env`. Las guías de operación y recuperación incorporan los cambios.

Razón social/NIT reales de la clínica solicitados para completar su configuración;
no se sustituyen por datos ficticios en la base local. Continúan las decisiones
clínicas y la validación de la futura VM indicadas en `estado_prompts.md`.

## 2026-11-12 · B18–B28: aprobación, recepción, seguimiento y preparación de despliegue

### Implementado

- **B18:** reglas de aprobación por rango de total/categoría, máximo de coincidencias,
  solicitud con contenido/política/cliente conservados, firmas distintas por ciclo,
  rechazo a borrador y emisión atómica con consecutivo. El usuario confirmó otra
  persona administradora distinta del elaborador y **PDF generado directamente**.
  FR-GDS-21 con datos congelados, fuentes incluidas, ítems/desglose y aprobadores;
  evidencia de envío con fecha y PDF privado opcional, sin enviar comunicaciones.
  Nombre/NIT de clínica requieren configuración antes de solicitar aprobación.
- **B19:** recepciones parciales/totales y ajustes inmutables por línea, aceptado,
  rechazado, pendiente, estado derivado, revisión esperada y soporte privado. Exceso
  requiere habilitación, autorización administrativa expresa y motivo. El usuario
  eligió solo administradores/desarrolladores; coordinador por área está preparado
  y deshabilitado inicialmente.
- **B20:** app `seguimientos`, tipos editables con cuatro valores iniciales,
  origen desde orden emitida o contrato aprobado, copia independiente de datos,
  corrección auditada e idempotencia. Creación automática al emitir, configurable,
  dentro de la transacción; un seguimiento por orden y uno principal por contrato.
- **B21–B22:** eventos inmutables con fecha del evento/registro, autor, tipo conservado,
  PDF y correcciones enlazadas. Entregas reutilizan el mismo libro de recepción:
  devoluciones reducen aceptado neto, ajustes conservan signos, cierre/reapertura
  de líneas exige motivo y conserva saldos. Cada movimiento genera evento enlazado
  que reutiliza el PDF, sin duplicar cantidades ni archivo.
- **B23–B24:** derivación pura de estados con fecha inyectada, hitos por tipo sin
  SLA reales precargados, versiones guardadas y adopción explícita, entrega esperada,
  panel de próximos vencimientos y comando `seguimientos_atrasados`. Cierre con
  resultado/fecha/autor, bloqueo o advertencia de saldo, orden cerrada compatible y
  reapertura administrativa auditada, inicialmente deshabilitada. El historial queda
  consultable. Prioridades, SLA y decisiones D-14/D-15 requieren validación clínica.
- **B25:** filtros combinables, paginación, estados derivados y Excel del mismo
  conjunto. Agregados en base de datos para valores y cantidades por unidad; total
  de órdenes separado de correcciones/contratos sin orden. Alcance de consulta futura
  de coordinadores limitado al área propia y deshabilitado inicialmente.
- **B26–B27:** revisión de permisos y PDF compartidos, referencias de envíos,
  recepciones y eventos incluidas en la limpieza segura. Componente de filtros y
  función de alcance antes de filtrar, listados por módulo, exportaciones coherentes
  y búsqueda superior por NIT canónico/formateado o consecutivo. Se mantienen las
  pruebas de protección de desarrolladores, portal y archivos transaccionales.
- **B28:** guía Ubuntu 24.04/Python 3.13/PostgreSQL 18, plantillas Gunicorn/nginx,
  entorno de producción con solo nombres de variables, rutas de privados/estáticos
  configurables y archivo de entorno externo. Respaldo con `pg_dump`, privados,
  SHA-256, bloqueo de ejecuciones simultáneas y retención configurable 7 diarios/4
  semanales; restauración con verificación y confirmación explícita del operador.
  No se desplegó, instaló VM ni programó una tarea en otro equipo.

### Verificación

- **31 pruebas nuevas**: aprobación/ciclos/PDF/soportes, recepción/excesos/ajustes,
  seguimiento/orígenes/eventos/devoluciones/hitos/cierre, reportes/Excel/filtros y
  respaldo/restauración. Se adaptaron los fixtures B16/B17 para usar solicitudes y
  firmas explícitas; ya no pueden emitir sin aprobación.
- Suite SQLite: **860 pruebas sin fallos**, con seis exclusivas de PostgreSQL omitidas.
- Suite PostgreSQL 18.6: **860 pruebas correctas**, incluidas respuestas simultáneas
  sin duplicar firma/número y `pg_dump`/`pg_restore` entre dos bases ficticias con
  comprobación de datos y PDF. Base de pruebas y bases de restauración aisladas;
  instancia temporal detenida al terminar. No se alteró PostgreSQL nativo ni `.env`.
- La verificación detectó y corrigió conexiones SQLite sin cerrar al retirar archivos
  temporales y el bloqueo de relaciones opcionales en PostgreSQL; ahora se bloquea
  expresamente la fila de seguimiento después de cotización/orden.
- `check`, `makemigrations --check --dry-run` y `migrate --check` correctos.
  `check --deploy --fail-level WARNING` sin advertencias activas con un entorno
  temporal ficticio de producción; se conserva la exclusión previa `axes.W006`.
  Se probaron explícitamente HSTS, subdominios y precarga en ese entorno, sin cambiar
  la política local. Sintaxis de `respaldo.sh` comprobada con `bash -n`.
- Respaldo previo a las migraciones con estructura/SHA-256 verificados:
  `C:\Users\USUARIO\AppData\Local\Temp\suministros-respaldos\diario-2026-11-12.tar.gz`.
  Migraciones locales aplicadas e integridad SQLite comprobada.
- App reiniciada en `http://127.0.0.1:8001/ingresar/`. HTTP 200 en ingreso/estilos,
  órdenes/reglas/retenciones, seguimiento/creación/hitos, listados/búsqueda para ambos
  roles, y administrador técnico para desarrollador. Contraseñas anteriores conservadas.
  Catálogos locales: 4 tipos de seguimiento, 8 tipos de evento, 4 resultados y **0 SLA**.
- Archivos de aplicación/documentación en UTF-8 y CRLF. Los archivos Linux `.sh`,
  `.service` y `.conf` usan LF explícito en `.gitattributes`.

Guías: `docs/aprobacion_recepcion_seguimientos.md` y `docs/despliegue.md`.
Los prompts técnicos restantes quedan atendidos; continúan pendientes la aceptación
de reglas D-01 a D-17 por la clínica y la instalación/validación de systemd, nginx,
certificados, carga y recuperación en la futura VM Ubuntu. No se crearon commits ni push.

## 2026-11-12 · B17: descuentos, impuestos y retenciones de órdenes

### Implementado

- Motor puro Decimal de importes, sin consultas a catálogos: bruto, descuento en
  dinero por línea, base neta/base gravable, impuesto, retenciones y total a pagar.
  Descuento antes o después del impuesto y redondeo por línea o al total; 0/1/2
  decimales y cuatro modos configurables. El redondeo al total distribuye residuos
  con desempate por posición y descuento limitado al bruto asignado. Las líneas
  suman exactamente la cabecera. Se rechazan floats, negativos, no finitos,
  escalas inválidas, descuentos excesivos y retenciones mayores al total.
- Catálogo de retenciones vacío inicialmente: nombre, porcentaje, base mínima
  opcional, base neta/bruta/con impuestos y estado activo. Administración con
  motivo y bitácora, permisos y CSRF. Selección a nivel de orden, mínimo inclusivo
  y foto incluso si no se alcanza el umbral. No hay porcentajes fiscales fijos.
- La creación conserva importes y reglas adjudicados. El borrador permite descuento
  por línea y selección expresa de tarifa activa, conservando originales y oferta.
  Parámetros actuales y actualización de retenciones requieren una opción explícita;
  un cambio de catálogo no sustituye fotos guardadas. Las retenciones guardadas
  inactivas se pueden conservar o retirar, pero no actualizar mientras estén inactivas.
- Reglas, bases y retenciones aparecen en detalle e historial. Las diferencias de
  reglas se describen con orden estable para evitar revisiones falsas por el orden
  de claves de JSONB en PostgreSQL. Permanece el control de revisión esperada y
  reversión conjunta de importes, historial y auditoría.
- El motor de emisión B16 valida líneas, reglas y cabecera antes de reservar número;
  guarda foto de descuentos, impuestos, retenciones y parámetros efectivamente usados.
  No consulta tarifas actuales al emitir. Emisión/anulación conservan esa foto.
  El flujo de aprobación y la emisión desde interfaz continúan en B18.
- Migraciones derivan bases de órdenes previas sin recalcular importes ni reescribir
  originales, revisiones o numeración. No fabrican fotos de emisión históricas.
  Nuevas restricciones protegen bases y retenciones. Guía con ejemplos fijos en
  `docs/importes_ordenes.md`. D-11 y los casos oficiales de financiera siguen pendientes.

### Verificación

- 19 casos nuevos de cálculo e integración: tabla fija ficticia, mezclas de tarifas,
  exentos, descuentos antes/después, umbrales, modos y reparto de redondeo, muchas
  líneas/importes grandes, conservación de catálogos y originales, migración,
  emisión inconsistente sin número, foto al emitir, permisos, CSRF y pantallas.
  Se marca explícitamente «pendiente de validar con financiera».
- SQLite: **829 pruebas sin fallos**, con cuatro exclusivas de PostgreSQL omitidas.
- PostgreSQL 18.6: **829 pruebas correctas**, incluidas las cuatro de concurrencia,
  en base temporal aislada. Instancia temporal detenida al finalizar; no se modificaron
  la base PostgreSQL nativa ni `.env`.
- `check` y `makemigrations --check --dry-run` correctos; archivos modificados en UTF-8/CRLF.
- Respaldo local verificado antes de migrar:
  `C:\Users\USUARIO\AppData\Local\Temp\suministros-respaldos\db-antes-b17-20261112-104555.sqlite3`.
- Migraciones locales aplicadas y `migrate --check` correcto; integridad SQLite verificada.
  Aplicación reiniciada en `http://127.0.0.1:8001/ingresar/`, con HTTP 200 en ingreso,
  estilos, inicio, órdenes y retenciones para ambos roles, y administrador técnico
  para desarrollador. Las dos cuentas locales conservan sus contraseñas anteriores.

Siguiente etapa: **B18, aprobar y emitir órdenes de compra**.

## 2026-11-12 · B16: consecutivo y validez de órdenes

- ContadorOrdenCompra con serie global o anual, valor no decreciente y admin técnico
  de solo lectura. Orden con número, consecutivo único, año/serie, reglas, fecha y
  responsable de emisión, fecha de validez opcional y metadatos de anulación.
  Restricciones de consecutivo, número/serie y numeración completa en base de datos.
- Parámetros D-12 de prefijo, incluir año, ancho mínimo y reinicio anual; iniciales
  provisionales OC/año/4 dígitos/sin reinicio. El año se toma de la emisión en Bogotá,
  no de la elaboración. Sobrepasar el ancho continúa sin truncar. Reinicio anual
  exige incluir año; cambios de formato/modo no reutilizan números históricos.
- Motor numerar_al_emitir para orden En aprobación sin número, con origen vigente.
  Bloquea cotización, orden, parámetros y contador; asigna y pasa a Emitida en una
  misma transacción con revisión, usuario, fecha y auditoría. Un fallo revierte también
  el contador. Dos solicitudes de la misma orden no consumen un segundo número.
- El flujo de aprobación y la emisión desde la interfaz se conectarán en B18: esta
  etapa no expone un botón de emisión directa. B18 deberá validar las aprobaciones
  y llamar el motor dentro de su propia transacción. Los borradores siguen sin número.
- Anulación administrativa con motivo y revisión esperada para borrador, En aprobación
  o Emitida sin recepción. Conserva número, formato, importes y emisión; registra actor,
  fecha, motivo y revisión. No libera contador ni reactiva la orden. Recepciones/cierre
  quedan sujetos a flujos posteriores; anular decisión conserva los metadatos de sus borradores.
- Fecha de validez opcional en creación/edición, con etiqueta D-13 configurable.
  Vacía permitida; si existe, no precede a elaboración. No se asume que sea fecha de
  entrega. Borradores usan la etiqueta actual y emisión conserva la etiqueta aplicada.
- Detalle/listado y revisiones muestran consecutivo y datos de emisión/anulación;
  formulario de anulación POST con permisos, motivo, revisión y CSRF. Modelo y contador
  protegidos frente a cambios de numeración. Guía en `docs/consecutivos_ordenes.md`.

### Verificación

- Suite SQLite: **810 pruebas sin fallos**, con cuatro pruebas exclusivas de
  concurrencia PostgreSQL omitidas. Veinticuatro pruebas nuevas sobre las 786 de B15.
- Suite PostgreSQL 18.6: **810 pruebas correctas**, incluidas las cuatro de concurrencia,
  en base temporal eliminada al terminar. Instancia temporal detenida. Python 3.13.15
  y Django 5.2.19.
- Pruebas nuevas: consecutivos normales, formatos/año de Bogotá, reinicio y cambio de
  modo, ancho superado, anulación sin reutilización, revisión atrasada, fuente inválida,
  rollback de auditoría, contador no decreciente, restricción única real, fecha/etiqueta,
  permisos y CSRF. Dos TransactionTestCase PostgreSQL verifican emisiones paralelas
  desde cotizaciones distintas y doble emisión de una misma orden.
- `check` sin errores, `makemigrations --check` sin cambios y `migrate --check`
  sin pendientes locales. Permanece `axes.W006` previamente silenciado.
- Migraciones `compras/0019–0020` y `parametros/0017` aplicadas a SQLite tras el respaldo
  `C:/Users/USUARIO/AppData/Local/Temp/suministros-respaldos/db-antes-b16-20261112-100435.sqlite3`.
- UTF-8 y CRLF comprobados en los archivos de esta etapa. Instancia PostgreSQL temporal
  con acceso solo por 127.0.0.1, sin alterar servicios/bases habituales ni `.env`.
- No se crearon commits ni push.

Siguiente etapa: **B17, cálculo configurable de importes de la orden**.

## 2026-11-12 · B15: órdenes desde decisión aprobada

- Modelos OrdenCompra, OrdenLinea y RevisionOrdenCompra. Orden con decisión,
  cotización, proveedor, evaluación de origen opcional, pago, fecha de elaboración,
  elaborada por, estado, importes y foto original. Líneas con referencia, descripción,
  especificación, unidad, cantidad, precio, tarifa/porcentaje, descuento y valores;
  vínculos a precio ofertado y línea de proyección cuando existen.
- Preparación sin escrituras y creación explícita de una orden en borrador por
  proveedor adjudicado. Requiere decisión aprobada con firmas y cotización Decidida.
  La operación completa es transaccional e idempotente por decisión/proveedor;
  repeticiones devuelven las órdenes existentes sin sobrescribir ediciones.
- Copia independiente de la selección B13, contrastada con la revisión inmutable B10.
  Copia NIT, razón social, contacto, cantidades, precios, tarifas, importes y reglas.
  No usa precios vivos ni porcentajes actuales. El pago inicial proviene de la foto
  contractual de aprobación B14, si existe, con opción de completarlo en el borrador.
- Edición con motivo de referencia/descripción/especificación/unidad/cantidad/precio,
  fecha y pago. Cantidad positiva, precio no negativo y escalas Decimal; rechazo de
  no finitos, flotantes, líneas ajenas/omitidas/repetidas y totales del cliente.
  Mantiene tarifa y redondeo de la oferta; descuento cero hasta la política B17.
- Conserva original y diferencias actuales de cada línea, marca de modificación y
  revisiones completas con actor/fecha/motivo. Restablecer al origen conserva la marca
  e historial. Control de revisión esperada y guardados sin cambios sin revisión nueva.
  Las ediciones de orden no modifican la oferta ni la adjudicación.
- Anular una decisión anula sus órdenes en borrador en la misma transacción, con
  revisión y bitácora, conservando fotos/importes. Si alguna avanzó del borrador,
  impide invalidar la decisión sin resolver primero esa orden. Un fallo de auditoría
  revierte también las anulaciones o la creación múltiple completa.
- Navegación orden → decisión/cotización → lista/cierre → FR14/proveedor → necesidad
  → proyección. La evaluación sale del cierre o verificación confirmada, nunca de
  una evaluación posterior tomada como si fuera el origen. Revisión de oferta
  conservada y contrato aprobados consultables desde cada orden.
- Pantallas de listado, preparación, detalle, edición y revisiones; enlaces desde
  decisión y cotización. Permisos administrativos, CSRF y admin técnico de solo lectura.
  Guía en `docs/ordenes_compra.md`. Numeración al emitir queda para B16 y la política
  completa de descuentos/retenciones/redondeos de orden para B17.

### Verificación

- Suite SQLite: **786 pruebas sin fallos**, con dos pruebas exclusivas de concurrencia
  PostgreSQL omitidas. Veintidós pruebas nuevas sobre las 764 de B14.
- Suite PostgreSQL 18.6: **786 pruebas correctas**, incluidas las dos de concurrencia,
  en base temporal eliminada al terminar. Instancia temporal detenida. Python 3.13.15
  y Django 5.2.19.
- Pruebas nuevas: una orden completa de 52 o dos de 10/40 por líneas, copia histórica
  frente a cambios de catálogo/proveedor/precio vivo, pago contractual, importes y
  redondeo conservados, original/actual, revisión esperada, idempotencia, anulación,
  reversión de auditoría, permisos, CSRF y trazabilidad real FR14/proyección.
- La prueba PostgreSQL de aprobación simultánea añade dos solicitudes concurrentes
  de creación desde esa decisión, verificando mismas órdenes y un único evento de creación.
- `check` sin errores, `makemigrations --check` sin cambios y `migrate --check`
  sin pendientes locales. Permanece `axes.W006` previamente silenciado.
  UTF-8 y CRLF comprobados en los archivos de esta etapa.
- Migración `compras/0018` aplicada a SQLite tras el respaldo
  `C:/Users/USUARIO/AppData/Local/Temp/suministros-respaldos/db-antes-b15-20261112-093608.sqlite3`.
- Se reutiliza la instancia temporal PostgreSQL 18.6 de pruebas con puerto aislado y
  acceso solo por 127.0.0.1, sin alterar servicios/bases habituales ni `.env`.
- No se crearon commits ni push.

Siguiente etapa: **B16, consecutivo de la orden al emitir**.

## 2026-11-12 · B14: contratos y pólizas

- Requiere contrato por cotización, con edición auditada antes de proponer y revisión
  esperada. El comparativo conserva la elección; el valor inicial No mantiene el
  comportamiento de propuestas anteriores a B14 sin invalidar sus firmas.
- Contrato opcional uno a uno con la decisión, con número, supervisor usuario activo
  o texto, nombre conservado, cargo, inicio/fin, forma de pago, valor Decimal y PDF.
  Borradores incompletos permitidos; no se presupone que el valor sea igual al adjudicado.
- Pólizas por contrato con tipo editable, aseguradora, número, valor asegurado,
  vigencias, PDF y activación. Catálogo inicial Cumplimiento, Calidad y Responsabilidad
  civil, con días de alerta generales o particulares. No establece amparos oficiales.
  Una póliza puede retirarse conservando el nombre aunque su tipo esté desactivado.
- Obligatoriedad configurable true/false por campo en contrato y póliza, más parámetro
  independiente de exigir alguna póliza. Inicial provisional con datos contractuales
  obligatorios/PDF opcional; datos y PDF de cada póliza activa obligatorios; tener alguna
  póliza es opcional. La clínica debe aprobar estos valores.
- Integración B13 antes de cada aprobación: una compra sin contrato no pide estos
  campos; con contrato exige registro y campos/pólizas según la regla vigente.
  Cada aprobación conserva foto contractual y reglas; cambiar obligatoriedad entre
  firmas exige nueva propuesta. Protección adicional de transición a Decidida con contrato.
- La primera firma protege contrato y pólizas, incluso con más aprobaciones pendientes.
  Anular conserva contratos/evidencias históricos y permite una nueva propuesta con
  su propio contrato. No se trasladan registros entre decisiones ni se copian automáticamente.
- Cada cambio de contrato o póliza incrementa una revisión contractual común, detecta
  formularios atrasados y conserva foto completa, usuario, fecha y motivo. Reemplazar
  o retirar PDF y desactivar pólizas conserva evidencias y revisiones inmutables.
- PDF privados de hasta 10 MB, extensión/cabecera, UUID, descarga administrativa
  acotada a cotización/decisión/adjunto, sin caché, nosniff y bitácora. Supervisor
  no obtiene permisos de descarga por su designación. Compensación de PDF nuevo si
  falla la operación/auditoría y rechazo de transacciones externas al cargar.
- Alertas reutilizan B3 a fecha explícita: vigente, por vencer inclusivo, vencida y
  sin vigencia acreditada para fechas futuras/incompletas. Umbral general o por tipo,
  incluido 0. Filtros de fecha/estado; tablero general excluye decisiones anuladas,
  que conservan consulta histórica. No se inventan bloqueos por vigencia no acordados.
- Pantallas de requerimiento, contrato, pólizas, revisiones, catálogo y alertas, con
  navegación y admin técnico de solo lectura. Guía en `docs/contratos_polizas.md`.

### Verificación

- Suite SQLite: **764 pruebas sin fallos**, con dos pruebas exclusivas de concurrencia
  PostgreSQL omitidas. Veintiocho pruebas nuevas sobre las 736 de B13.
- Suite PostgreSQL 18.6: **764 pruebas correctas**, incluidas las dos de concurrencia,
  en base temporal eliminada al terminar. Instancia temporal detenida. Python 3.13.15
  y Django 5.2.19. Ambas suites se repitieron tras el ajuste final de retirada de pólizas.
- Pruebas nuevas: compra con/sin contrato, campos y pólizas exigibles, supervisor,
  fechas/importes, alertas inclusivas y futuras, catálogos, revisión esperada, firma,
  cambios de obligatoriedad entre firmas, PDF privados/históricos, compensación,
  identidad, permisos, CSRF y filtros. La prueba de aprobación simultánea B13 usa
  ahora contrato completo y exige una sola decisión final.
- `check` sin errores, `makemigrations --check` sin cambios y `migrate --check`
  sin pendientes locales. Permanece `axes.W006` previamente silenciado.
  UTF-8 y CRLF comprobados en los archivos de esta etapa.
- Migraciones `compras/0016–0017` y `parametros/0016` aplicadas a SQLite tras el respaldo
  `C:/Users/USUARIO/AppData/Local/Temp/suministros-respaldos/db-antes-b14-20261112-091202.sqlite3`.
- Se reutiliza la instancia temporal PostgreSQL 18.6 de pruebas con puerto aislado y
  acceso solo por 127.0.0.1, sin alterar servicios/bases habituales ni `.env`.
- No se crearon commits ni push.

Siguiente etapa: **B15, órdenes de compra desde la decisión aprobada**.

## 2026-11-12 · B13: comparativo y decisión de cotización

- Comparativo con especificaciones como filas y oferentes como columnas, precios,
  subtotales, impuestos y totales guardados. El costo homogéneo es total con impuestos;
  el menor por línea y los empates se resaltan en azul claro #dbeafe. Muestra también
  totales por oferente, verificaciones B11 y puntaje/puesto del cierre exacto de elegibles.
- Modalidades de oferta completa y adjudicación de cada línea a un oferente.
  El usuario eligió Oferta completa como valor inicial; permanece configurable.
  Selección completa y sin líneas repetidas, omitidas ni ofertas ajenas. Elección
  más costosa exige justificación adicional; recomendación y motivo son obligatorios.
- Propuesta con foto inmutable de comparación, selección, reglas y caso B12.
  El formulario firma la comparación mostrada y rechaza una vista previa alterada
  o desactualizada. Crear propuesta deja la cotización En comparación sin decidirla.
- Aprobaciones de usuarios distintos, configurables en cantidad y roles. Inicial
  provisional de una aprobación de administrador. Se fijan cantidad, roles y
  control de verificaciones en cada propuesta; cambios de esos parámetros afectan
  propuestas nuevas. El usuario debe conservar un rol habilitado al aprobar.
- Cada firma revalida ofertas, verificaciones, obligatoriedad y caso B12. Cambios
  exigen anular y proponer de nuevo, sin trasladar aprobaciones anteriores. B12
  comprueba justificación/evidencia según reglas vigentes; las verificaciones activas
  obligatorias de oferentes seleccionados requieren justificación en modo advertir
  o impiden continuar en modo bloquear. Estados de revisión anterior son Pendiente.
- La última firma registra decidido por/fecha y pasa la cotización a Decidida.
  Ofertas, verificaciones y proveedor único quedan en solo lectura. El bloqueo
  transaccional impide registrar dos decisiones finales ante aprobaciones simultáneas.
- Anulación con motivo de propuestas o decisiones, conservando foto, adjudicaciones,
  aprobaciones y metadatos. Devuelve la cotización a En comparación; cambios posteriores
  se registran en una nueva propuesta. Fallos de auditoría revierten la operación completa.
- Excel con comparativo, verificaciones, elegibles de origen, decisión y aprobaciones,
  menores resaltados y textos sin fórmulas. Cada decisión permite exportar su foto
  histórica incluso después de anular y cambiar las ofertas.
- Pantallas y enlaces desde cotización/oferta, servicios con permisos administrativos,
  CSRF y descargas Excel auditadas. Modelos nuevos en admin técnico de solo lectura.
  Guía en `docs/decision_cotizacion.md`. No se crean contratos ni órdenes al decidir.

### Verificación

- Suite SQLite: **736 pruebas sin fallos**, con dos pruebas exclusivas de concurrencia
  PostgreSQL omitidas. Veintinueve pruebas nuevas sobre las 707 de B12.
- Suite PostgreSQL 18.6: **736 pruebas correctas**, incluidas las dos de concurrencia,
  en base temporal eliminada al terminar. Instancia temporal detenida. Python 3.13.15
  y Django 5.2.19.
- Pruebas nuevas: datos manuales 70/52 por oferta y 50 por líneas, impuestos y empates,
  justificaciones, selección inválida, N firmas, permisos de aprobación, cambios entre
  firmas, B11/B12, foto de elegibles real, anulación, compensación de auditoría,
  Excel histórico sin fórmulas, CSRF y aprobación concurrente con un solo cierre.
- `check` sin errores, `makemigrations --check` sin cambios y `migrate --check`
  sin pendientes locales. Permanece `axes.W006` previamente silenciado.
  UTF-8 y CRLF comprobados en los archivos de esta etapa.
- Migraciones `compras/0015` y `parametros/0015` aplicadas a SQLite tras el respaldo
  `C:/Users/USUARIO/AppData/Local/Temp/suministros-respaldos/db-antes-b13-20261112-084932.sqlite3`.
- Se reutiliza la instancia temporal PostgreSQL 18.6 de las pruebas B12, con puerto
  aislado y acceso solo por 127.0.0.1, sin alterar servicios/bases habituales ni `.env`.
- No se crearon commits ni push.

Siguiente etapa: **B14, contratos y pólizas**.

## 2026-11-12 · B12: proveedor único en la cotización

- Campo de proveedor único en cotización, causal configurable, justificación,
  evidencia opcional, revisión, reglas e identidad de la oferta/proveedor usados.
  Se sugiere solo cuando existe una oferta registrada; abrir la pantalla no escribe.
  Los invitados sin oferta no se cuentan.
- Causales iniciales editables Exclusividad, Representación de marca, Urgencia y
  Otra, con descripción, orden, activación y bitácora. El nombre confirmado queda
  conservado aunque después se renombre o desactive la causal.
- Parámetros provisionales: mínimo 20 caracteres de justificación y PDF opcional.
  Mínimo entero desde 1, normalización de espacios y prohibición de texto vacío.
  La clínica debe aprobar los valores; no se presentan como política oficial.
- Marcar exige exactamente una oferta, causal activa, justificación y evidencia
  según el parámetro. Desmarcar limpia el caso actual y conserva su historial.
  Cada operación exige motivo y registra usuario, fecha, reglas y foto del proveedor.
  Una revisión esperada evita sobrescribir cambios hechos mientras se revisaba.
- Validador de servicio para B13: sin ofertas no permite decidir; con una oferta
  exige confirmar y justificar el caso, incluso si se desmarcó. Comprueba evidencia
  y mínimo vigentes, identidad y número actual de ofertas. Devuelve una foto sin
  decidir. B13 deberá invocarlo en su transacción y conservarla con la decisión.
- Protección adicional al guardar el modelo en Decidida, validando los valores que
  se persistirán; actualizaciones masivas de estado o campos del caso bloqueadas.
  La pantalla de decisión completa se implementará en B13.
- PDF privados de hasta 10 MB, extensión/cabecera, UUID y descarga administrativa
  acotada por cotización, sin caché, con nosniff y bitácora. Reemplazar, retirar o
  desmarcar conserva archivos y revisiones anteriores inmutables. El borrado seguro
  compartido reconoce referencias de estas nuevas evidencias.
- Transacción durable al cargar, rechazo de transacciones externas y compensación
  del PDF nuevo ante errores de validación/auditoría. Decidida y Anulada solo
  permiten consultar el caso. Pantallas de caso, revisiones y causales, con enlaces
  desde compras, configuración y cotización. Admin técnico en solo lectura.
- Guía en `docs/proveedor_unico_cotizacion.md` y hoja de ruta actualizada a B13.

### Verificación

- Suite SQLite: **707 pruebas sin fallos**, con una prueba exclusiva de concurrencia
  PostgreSQL omitida. Veintidós pruebas nuevas sobre las 685 de B11.
- Suite PostgreSQL 18.6: **707 pruebas correctas** en base temporal aislada,
  eliminada al terminar; instancia temporal detenida. Python 3.13.15 y Django 5.2.19.
- Pruebas nuevas: sugerencia sin escrituras, causal, espacios/mínimo, evidencia
  configurable, decisión sin caso, cambio de reglas/ofertas, guardado de estado,
  revisión esperada, historial, PDF privados, compensación, permisos y CSRF.
  Las pruebas previas de solo lectura preparan un caso válido antes de Decidida.
- `check` sin errores, `makemigrations --check` sin cambios y `migrate --check`
  sin pendientes locales. Permanece `axes.W006` previamente silenciado.
  UTF-8 y CRLF comprobados en los archivos de esta etapa.
- Migraciones `compras/0013–0014` y `parametros/0014` aplicadas a SQLite tras el respaldo
  `C:/Users/USUARIO/AppData/Local/Temp/suministros-respaldos/db-antes-b12-20261112-081943.sqlite3`.
- El puerto configurado 5434 no respondía y las credenciales del proyecto no
  correspondían a la instancia nativa activa. Se preparó una instancia PostgreSQL
  18.6 temporal con acceso solo local y puerto aislado para las pruebas.
  Se conserva `.env` y las bases/servicios PostgreSQL habituales.
- La base de pruebas se eliminó y la instancia temporal quedó detenida. La
  revisión automática bloqueó la limpieza de sus directorios temporales; se
  conservaron en la carpeta temporal de Windows, sin un servidor activo.
- No se crearon commits ni push.

Siguiente etapa: **B13, comparativo y decisión de la cotización**.

## 2026-11-11 · B11: verificaciones por oferente

- Catálogos `TipoVerificacion` y `EstadoVerificacion` con orden y activación,
  obligatoriedad/origen y clasificación semántica. Se precargan Vigencia documental,
  Requisitos técnicos, Sarlaft y Sicof como opcionales, y Sí/No/Pendiente/N/A.
  La clínica debe definir las obligaciones oficiales; no se inventan controles externos.
- `VerificacionOferta` única por oferta/tipo, con estado, fecha, responsable,
  observación, evidencia opcional y revisión de oferta. Cada confirmación conserva
  una revisión inmutable con nombres, significado, propuesta, actor, motivo y PDF.
  Cambiar catálogos o renovar documentos no reescribe lo confirmado.
- Matriz de oferentes × tipos con alertas para activos obligatorios en No,
  Pendiente o sin confirmar. Cambiar la revisión de oferta exige reconfirmación;
  se mantiene el estado histórico. Tipos inactivos con registros siguen consultables.
- Propuesta documental reutiliza B3 a fecha elegida, con categoría y versión de la
  última FR14 finalizada no anulada cuya fecha no exceda la consulta, o categoría
  actual si no existe. Se usa el catálogo de exigencias configurado al consultar.
  Obligatorios vencidos/faltantes proponen No, opcionales con alertas o catálogo
  vacío proponen Pendiente, y vigentes/próximos proponen Sí.
- Consultar la propuesta no escribe registros. Confirmación expresa y firma del
  contenido mostrado impiden aceptar propuestas alteradas o cambiadas; apartarse
  del resultado requiere observación. La foto conserva documentos y fechas usados.
  Sarlaft/Sicof y requisitos técnicos comienzan como verificaciones manuales.
- PDF privados con validación existente de extensión, cabecera y 10 MB, UUID,
  descarga administrativa acotada a cotización/oferta/verificación/adjunto,
  sin caché, `nosniff` y bitácora. Reemplazo o retirada conserva evidencias anteriores.
  El borrado seguro compartido reconoce referencias de las nuevas evidencias.
- Transacción durable al cargar archivos, rechazo de transacciones externas y
  compensación del PDF nuevo si falla validación/auditoría. Cotización decidida o
  anulada es de solo consulta; revisiones y PDF históricos no admiten cambios.
- Pantallas de matriz, confirmación, historial y catálogos, enlazadas desde compras,
  configuración, cotización y oferta. Modelos en solo lectura en el admin técnico.
  Guía en `docs/verificaciones_ofertas.md`.

### Verificación

- Suite SQLite: **685 pruebas sin fallos**, con una prueba de concurrencia
  exclusiva de PostgreSQL omitida. Diecisiete pruebas nuevas sobre las 668 de B10.
- Suite PostgreSQL 18.6: **685 pruebas correctas** en base temporal aislada,
  eliminada al terminar. Python 3.13.15 y Django 5.2.19.
- Pruebas nuevas: cuatro estados con usuario/fecha, obligatoriedad, catálogos,
  documentos y evaluación FR14 a fecha, exclusión de registros futuros, propuesta
  firmada y confirmación explícita, revisión de oferta, historial, evidencia privada,
  reversión de archivos, permisos y CSRF.
- `check` sin errores, `makemigrations --check` sin cambios y `migrate --check`
  sin pendientes locales. Permanece `axes.W006` previamente silenciado.
  UTF-8 y CRLF conservados en los archivos de esta etapa.
- Migraciones `compras/0011–0012` aplicadas a SQLite tras el respaldo
  `C:/Users/USUARIO/AppData/Local/Temp/suministros-respaldos/db-antes-b11-20261111-142949.sqlite3`.
- Se conserva `.env` y la base PostgreSQL habitual. No se crearon commits ni push.

Siguiente etapa: **B12, proveedor único en la cotización**.

## 2026-11-11 · B10: ofertas, precios e impuestos por proveedor

- `Oferta` única por cotización/proveedor y NIT, con contacto, fecha, vigencia
  opcional, observación, importes calculados y reglas guardadas. `OfertaLinea`
  conserva cantidad/especificación de cotización, precio, tarifa y porcentaje aplicados.
- Cada guardado conserva `RevisionOferta` inmutable con datos y PDF de ese momento;
  no genera varias ofertas simultáneas del mismo proveedor. La revisión esperada
  detecta ediciones concurrentes y evita sobrescribir un guardado posterior.
- Proveedores nuevos usan la ficha existente antes de ser invitados. Cotizaciones
  manuales pueden invitar registrados con motivo y límite D-10; las provenientes
  de elegibles conservan los elegidos de la lista cerrada.
- Catálogo `TarifaImpuesto` configurable y desactivable, con porcentaje 0–100.
  Se precarga únicamente Exento/No gravado al 0 %; no se inventa IVA fijo. Nombre
  y porcentaje quedan conservados en las líneas, sin recalcular registros al editar el catálogo.
- Cálculo Decimal en servidor: subtotal de línea redondeado de cantidad × precio,
  impuesto redondeado sobre ese subtotal y total como suma. Encabezado suma líneas.
  Parámetros D-11 de decimales 0/1/2 y modo ROUND_HALF_UP/HALF_EVEN/DOWN/UP; inicial
  a pesos con ROUND_HALF_UP. No se aceptan totales del navegador ni descuentos implícitos.
- Ejemplos manuales ficticios: 2,5 × 100,15 con tarifa 19 % da 250 + 48 = 298 a
  pesos; a dos decimales da 250,38 + 47,57 = 297,95. D-11 sigue pendiente de aprobación.
- Captura de todas las líneas, sin mezcla entre cotizaciones ni oferentes. Valida
  precios finitos no negativos, escala decimal, vigencia, tarifas activas y estado;
  solo se modifica en borrador/en comparación. Decidida/anulada queda en solo lectura.
- PDF opcional privado con validación existente de extensión, cabecera y 10 MB,
  nombres UUID y descarga administrativa acotada a cotización/oferta/adjunto.
  Reemplazo o retirada conserva PDF anteriores; se amplió el borrado seguro compartido
  para reconocer referencias `PdfOferta` y evitar eliminar evidencias históricas.
- Guardado de archivo en transacción durable, con rechazo de transacciones externas.
  Error de validación/auditoría revierte oferta, precios, revisión y adjunto, y elimina
  solo el PDF nuevo no confirmado. Se verifica que un reemplazo fallido conserve el anterior.
- Pantallas de captura, detalle, revisiones y tarifas; enlaces desde cotización,
  descargas sin caché/nosniff y bitácora de cada mutación/descarga. Admin técnico en solo lectura.
- Guía en `docs/ofertas.md`. No se deciden cotizaciones ni se crean órdenes al guardar.

### Verificación

- Suite SQLite: **668 pruebas sin fallos**, con una prueba exclusiva de concurrencia
  PostgreSQL omitida. Veintidós pruebas nuevas sobre las 646 de B9.
- Suite PostgreSQL 18.6: **668 pruebas correctas** en base temporal aislada, eliminada
  al terminar. Python 3.13.15 y Django 5.2.19.
- Pruebas nuevas: importes manuales y redondeos, exentos/tarifas distintas, campos
  inválidos, separación de cotizaciones/oferentes, identidad, revisiones, estados,
  invitaciones, PDF privados/reemplazo/compensación, permisos, CSRF y totales manipulados.
- `check` sin errores, `makemigrations --check` sin cambios y `migrate --check` sin
  pendientes locales. Permanece `axes.W006` previamente silenciado. UTF-8 y CRLF conservados.
- Migraciones `compras/0009–0010` y `parametros/0013` aplicadas a SQLite tras el respaldo
  `C:/Users/USUARIO/AppData/Local/Temp/suministros-respaldos/db-antes-b10-20261111-140711.sqlite3`.
- Se conserva `.env` y la base PostgreSQL habitual. No se crearon commits ni push.

Siguiente etapa: **B11, verificaciones documentales, técnicas y Sarlaft/Sicof**.

## 2026-11-11 · B9: encabezado y líneas de cotización FR-GDS-28

- Modelos `Cotizacion`, `LineaCotizacion`, `InvitadoCotizacion`, `TipoCotizacion`
  y secuencia interna. Cotización siempre ligada a necesidad y área, con fecha,
  responsable, objeto, tipo, estado inicial borrador y consecutivo legible.
- Creación manual y desde lista cerrada mediante formulario explícito. Conserva
  la lista y su cierre histórico exactos; copia el objeto/líneas de origen e invita
  únicamente a participantes con cantidad autorizada positiva, con identidad y
  cantidad conservadas. Una invitación todavía no es una oferta.
- Especificaciones con descripción, unidad activa del catálogo existente, cantidad
  Decimal positiva y texto técnico. Relación opcional a `OrigenNecesidad`, validada
  contra la misma necesidad y, desde lista, contra el cierre elegido. Foto del origen
  y texto de unidad conservados. No se inventan conversiones de unidades.
- Consecutivo `COT-año-número global`, sin reinicio anual, con bloqueo transaccional
  y unicidad. Validación y auditoría fallidas revierten también la secuencia.
- Parámetros D-10: 3 invitados y 10 líneas inicialmente; 0 elimina el límite de
  negocio. Se conservan los límites aplicados. No se truncan líneas ni se descartan
  elegidos silenciosamente al excederlos. Valores provisionales pendientes de aprobación.
- Tipos Compra/Servicio/Contrato como catálogo inicial editable, desactivable y
  auditado. Formularios de encabezado, líneas dinámicas, tipos, listado y detalle.
- Navegación desde cotización hacia necesidad, lista, cierre y proyección; necesidad
  y lista muestran sus cotizaciones. Se completa la asociación real de B8: la lista
  pasa a Con cotización y se bloquea reabrir/anular. Creación y transiciones comparten
  bloqueo de necesidad/lista. Revisión firmada detecta precargas de cierres anteriores.
- Todas las mutaciones requieren rol administrativo y motivo, con bitácora
  transaccional. CSRF en formularios y modelos en solo lectura en el admin técnico.
  Abrir la precarga no crea registros; no se crean ofertas, impuestos ni órdenes.
- Guía en `docs/cotizaciones.md`; integración y límites actualizados en README,
  estado de prompts y guía de cierres. Siguiente etapa: B10, captura de ofertas.

### Verificación

- Suite SQLite: **646 pruebas sin fallos**, con una prueba exclusiva de concurrencia
  PostgreSQL omitida. Dieciséis pruebas nuevas sobre las 630 de B8.
- Suite PostgreSQL 18.6: **646 pruebas correctas** en base temporal aislada, eliminada
  al terminar. Python 3.13.15 y Django 5.2.19.
- Pruebas nuevas: creación manual y desde lista, vínculo a origen/proyección,
  invitados elegidos, límites exactos y configuración 0, cantidades inválidas,
  tipos/unidades inactivos, NIT único, consecutivos/reversión, firma de origen,
  bloqueo de reapertura con cotización real, navegación, permisos y CSRF.
- `check` sin errores, `makemigrations --check` sin cambios y `migrate --check` sin
  pendientes locales. Sintaxis JavaScript comprobada con `node --check`. Permanece
  `axes.W006` previamente silenciado. UTF-8 y CRLF conservados.
- Migraciones `compras/0007–0008` y `parametros/0012` aplicadas a SQLite tras el respaldo
  `C:/Users/USUARIO/AppData/Local/Temp/suministros-respaldos/db-antes-b9-20261111-134622.sqlite3`.
- Se conserva `.env` y la base PostgreSQL habitual. No se crearon commits ni push.

Siguiente etapa: **B10, ofertas, precios e impuestos por proveedor**.

## 2026-11-11 · B8: cierre, reapertura, anulación y transición de elegibles

- Cierre transaccional con bloqueo de necesidad/lista, decisión vigente B5/B6 y
  comprobación documental B7 a la fecha actual de Bogotá. Guarda usuario y fecha;
  las advertencias exigen justificación y los bloqueos no se omiten con texto.
- Foto completa de criterios, reglas, resultados, puestos, desempates, cantidades,
  decisiones y origen. Integra la referencia fija FR14 y la foto documental B7.
  Las consultas de matriz/puestos/Excel de listas cerradas leen esos datos conservados.
- `CierreListaElegibles`: archivo inmutable de cada ciclo, con motivo, responsable,
  fecha, resultado y documentos; consulta desde el historial de la lista. Los ciclos
  anteriores sobreviven a reaperturas, nuevos cierres y anulación, sin sobrescritura.
- Reapertura con motivo mientras no haya cotización asociada: conserva respuestas
  y cantidades para revisión, libera fotos activas y exige registrar la decisión
  otra vez. Renueva el control documental al siguiente cierre.
- Anulación de borrador o cerrada con actor/fecha/motivo, conservando datos y cierres.
  La anulación es terminal; una asociación a cotización impide reabrir o anular.
- Estados por lista en las necesidades: Borrador, Cerrada, Con cotización y Anulada.
  Acciones POST protegidas por rol y CSRF. Las listas cerradas/anuladas permanecen
  en solo lectura para participantes, calificaciones, decisiones y documentación.
- Botón Iniciar cotización solo en cerradas, con URL y servicio de precarga desde
  la foto completa: necesidad, líneas y proveedores elegidos con cantidad positiva.
  Es consulta sin escrituras; cerrar, calificar o preparar no crea cotizaciones ni órdenes.
- Contrato B9: detector del futuro `compras.Cotizacion.lista_elegibles`, con creación
  serializada sobre la lista. La prueba de asociación usa el adaptador simulado;
  el modelo y su prueba de integración real corresponden a B9. No se creó un modelo
  ficticio ni registros de cotización anticipados.
- Listas anteriores sin cierre completo se señalan expresamente; no se inventan
  actor ni fecha. La guía `docs/cierres_elegibles.md` explica revisión y transiciones.

### Verificación

- Suite SQLite: **630 pruebas sin fallos**, con una prueba exclusiva de concurrencia
  PostgreSQL omitida. Dieciséis pruebas nuevas sobre las 614 de B7.
- Suite PostgreSQL 18.6: **630 pruebas correctas** en base temporal aislada, eliminada
  al terminar. Python 3.13.15 y Django 5.2.19.
- Pruebas nuevas: cierre con actor/fecha/fotos, validaciones B5/B6/B7, reversión de
  estado/fotos/auditoría ante fallo, archivo inmutable, reapertura y segundo cierre,
  anulación, asociación simulada, lectura de foto, desempate/Excel, precarga sin
  escrituras, listado de estados, permisos, CSRF y métodos HTTP.
- `check` sin errores, `makemigrations --check` sin cambios y `migrate --check` sin
  pendientes locales. Permanece `axes.W006` previamente silenciado. UTF-8 y CRLF conservados.
- Migración `compras/0006` aplicada a SQLite tras el respaldo
  `C:/Users/USUARIO/AppData/Local/Temp/suministros-respaldos/db-antes-b8-20261111-132718.sqlite3`.
- Se conserva `.env` y la base PostgreSQL habitual. No se crearon commits ni push.

Siguiente etapa: **B9, encabezado y líneas de cotización FR-GDS-28**.

## 2026-11-11 · B7: vínculo de elegibles con FR-GDS-14 y documentos

- Pantalla por lista con la evaluación vigente de cada participante según FR14:
  última finalizada no anulada. Muestra calificación, fecha, categoría/versión y
  enlace; identifica ausencia, antigüedad y fecha futura sin presentar vigencia falsa.
- Reutiliza el tablero B3 con categoría y versión de la evaluación y referencia
  actual de Bogotá. Documentos exigidos con requisito, obligatoriedad, estado,
  expedición, vencimiento, plazo de alerta e identificador del soporte.
- Parámetros provisionales `elegibles.control_documental` (advertir por defecto o
  bloquear) y `elegibles.antiguedad_evaluacion_meses` (12 por defecto). Meses
  calendario con ajuste de último día; el aniversario es válido, el día siguiente antiguo.
- Para elegidos con cantidad positiva: advertir exige justificar las alertas;
  bloquear impide continuar sin FR14 vigente o con documentos obligatorios vencidos.
  Faltantes y vencidos opcionales requieren justificación cuando se permite continuar;
  próximos a vencer son informativos. No se inventa un bloqueo adicional D-05.
- Guardado auditado de justificación en borrador, con comprobación de condiciones
  actuales. El cierre debe volver a verificarlas; una justificación no omite bloqueos.
- Referencia fija FR14 y foto documental por participante, con reglas, referencia,
  justificación, actor y fecha en la lista. Servicio `conservar_al_cerrar` preparado
  para la transacción de cierre B8: exige lista cerrada, ausencia de captura previa
  y validación documental; un fallo revierte todas las fotos y sus registros.
- Consulta histórica de listas cerradas/anuladas sin recalcular con evaluaciones,
  documentos o parámetros nuevos. Las anteriores sin foto se identifican expresamente.
  No se duplican PDF ni se publican rutas privadas.
- Excel incorpora hoja Estado documental con evaluación, alertas y soportes,
  diferenciando consulta actual e histórica. Conserva permisos y tratamiento seguro
  de textos. Guía en `docs/vinculo_documental_elegibles.md`.
- La acción de cerrar, reapertura, anulación y transición siguen para B8. B7 prepara
  sus validadores y captura, probados mediante cierre simulado dentro de una transacción.
  Valores iniciales y exigencias oficiales D-05 siguen pendientes de aprobación de la clínica.

### Verificación

- Suite SQLite: **614 pruebas sin fallos**, con una prueba exclusiva de concurrencia
  PostgreSQL omitida. Quince pruebas nuevas sobre las 599 de B6.
- Suite PostgreSQL 18.6: **614 pruebas correctas** en base temporal aislada, eliminada
  al terminar. Python 3.13.15 y Django 5.2.19.
- Pruebas nuevas: evaluación vigente/antigua/futura, meses calendario, documentos,
  ambos modos, elegidos/no elegidos, justificación, foto fija, atomicidad, permisos,
  CSRF y Excel. Verifican que una evaluación nueva no cambie la referencia conservada.
- `check` sin errores, `makemigrations --check` sin cambios y `migrate --check` sin
  pendientes locales. Permanece `axes.W006` previamente silenciado. UTF-8 y CRLF conservados.
- Migraciones `compras/0005` y `parametros/0011` aplicadas a SQLite tras el respaldo
  `C:/Users/USUARIO/AppData/Local/Temp/suministros-respaldos/db-antes-b7-20261111-125650.sqlite3`.
- Se conserva `.env` y la base PostgreSQL habitual. No se crearon commits ni push.

Siguiente etapa: **B8, cierre, reapertura, anulación y transición a cotización**.

## 2026-11-11 · B6: puestos y decisión en listas de elegibles

- Puestos por total Decimal descendente, con ranking denso y bandera visible de
  empate. Participantes incompletos no reciben puesto y bloquean la decisión.
- Desempate manual por selectores de nombre/NIT, con todos los integrantes del
  grupo exactamente una vez, justificación, usuario, fecha y bitácora. Conserva
  el puesto calculado y muestra el puesto con desempate. Restablecimiento con motivo.
- Cantidad base explícita y unidad por necesidad, opcionales al crearla. Cuando
  falta base explícita, se suman los orígenes únicamente si comparten unidad.
  Necesidades manuales o con unidades mixtas requieren definir una base comparable;
  no se inventan conversiones. D-09 sigue pendiente y no se crean reservas entre listas.
- Cantidad autorizada Decimal no negativa por participante, observación y
  justificación de elección. El servidor valida el total contra la base y exige
  justificación para exceso de cantidad, elección fuera del primer puesto y proveedor
  único. Se conserva responsable y fecha de las asignaciones y decisión.
- Registro transaccional de la decisión con foto de puntajes, puestos, cantidades,
  versión y reglas. Cambiar calificaciones o participantes invalida decisión y
  desempates; cambiar cantidad base o desempate exige revisar la decisión. Un
  guardado de calificaciones sin cambios conserva su vigencia. El formulario detecta
  cambios de puntajes, puestos, cantidades y asignaciones antes de guardar.
- Solo se edita en borrador. Cambiar la base queda bloqueado si alguna lista de la
  necesidad está cerrada/anulada. `validar_para_cierre` comprueba las reglas de decisión
  y queda preparado para B8; esta etapa no cierra listas ni crea cotizaciones/órdenes.
- Excel con hojas Elegibles, Calificaciones y Decisión y reglas: puntajes, puestos,
  cantidades, unidades, observaciones, justificaciones, responsables y fechas.
  Estilos del consolidado, paneles inmovilizados, formatos numéricos y valores
  calculados en servidor. Textos y NIT se escriben sin fórmulas; descarga protegida,
  sin caché y auditada. Identifica decisiones pendientes y reglas provisionales.
- D-08 permanece pendiente de aprobación de la clínica. Guía en
  `docs/decision_elegibles.md`; siguiente etapa B7, vínculo documental FR-GDS-14.

### Verificación

- Suite SQLite: **599 pruebas sin fallos**, con una prueba exclusiva de concurrencia
  PostgreSQL omitida. Diecisiete pruebas nuevas sobre las 582 de B5.
- Suite PostgreSQL 18.6: **599 pruebas correctas** en base temporal aislada, eliminada
  al terminar. Python 3.13.15 y Django 5.2.19.
- Pruebas nuevas cubren puestos, empates, desempate y restablecimiento, proveedor único,
  excepciones, cantidades, unidades, invalidación, atomicidad, Excel, permisos y CSRF.
- `check` sin errores, `makemigrations --check` sin cambios y `migrate --check` sin
  pendientes locales. Permanece `axes.W006` previamente silenciado. UTF-8 y CRLF conservados.
- Migración `compras/0004` aplicada a SQLite tras el respaldo
  `C:/Users/USUARIO/AppData/Local/Temp/suministros-respaldos/db-antes-b6-20261111-123934.sqlite3`.
- Se conserva `.env` y la base PostgreSQL habitual. No se crearon commits ni push.

Siguiente etapa: **B7, vínculo con evaluación FR-GDS-14 y estado documental**.

## 2026-11-11 · B5: criterios y calificación ponderada de elegibles

- Catálogo `VersionCriterios` / `CriterioElegible` con edición en borrador, copia,
  publicación con vigencia y sucesión sin solapamientos. Una versión publicada
  conserva nombres y pesos, con protección también en guardado y operaciones ORM.
- Criterios iniciales en versión 1 en borrador: Administrativos 30 %, Precio 20 %,
  Valor agregado 20 % y Certificaciones 30 %. No se publica ni se declara aprobado
  automáticamente el catálogo. Se admiten uno a veinte criterios distintos y los
  pesos positivos con dos decimales deben sumar exactamente 100 %.
- Parámetro D-07 `elegibles.reglas_calculo`: escala inicial 5/3/1, método directo y
  aviso pendiente. Admite método escalado y escala configurable, con validación
  estricta de valores decimales, duplicados, rango y máximo positivo.
- Las nuevas listas toman la versión aplicable a su fecha y conservan las reglas.
  Las anteriores o creadas sin versión publicada quedan pendientes de asignación
  explícita en borrador. No se reasignan versiones ni reglas de listas configuradas.
- Matriz por lista con participantes activos, cumplimiento, observación, subtotal
  y total por proveedor. Cada celda es única y se audita con motivo; guardado
  transaccional que rechaza criterios ajenos, participantes retirados, valores
  fuera de escala y listas cerradas/anuladas. Token firmado detecta cambios de
  participantes o criterios mientras se diligencia el formulario.
- Cálculo Decimal en servidor: directo = cumplimiento × peso % / 100; escalado =
  cumplimiento / máximo de escala × peso %. Cada subtotal se redondea a cuatro
  decimales con ROUND_HALF_UP y el total suma los subtotales mostrados. Respuestas
  pendientes dejan el total incompleto; cero solo es válido si está en la escala.
- Ejemplo manual probado: cumplimientos 5/3/1/5 con pesos 30/20/20/30 producen
  **3,8000 / 5** directo y **76,0000 / 100** escalado. D-07 y el ejemplo funcional
  siguen pendientes de aprobación de la clínica; las pruebas no sustituyen esa aprobación.
- Publicar sucesoras o cambiar parámetros no altera listas configuradas ni
  cerradas. Retirar participantes conserva sus respuestas y reactivarlos las recupera.
- Guía en `docs/calificacion_elegibles.md`, con fórmulas, uso, límites y ejemplo.
  Puestos y decisión quedan para B6; vínculo documental y cierre para B7–B8.

### Verificación

- Suite SQLite: **582 pruebas sin fallos**, con una prueba exclusiva de concurrencia
  PostgreSQL omitida. Dieciséis pruebas nuevas sobre las 566 de B4.
- Suite PostgreSQL 18.6: **582 pruebas correctas** en base temporal aislada, eliminada
  al terminar. Python 3.13.15 y Django 5.2.19.
- `check` sin errores, `makemigrations --check` sin cambios y `migrate --check` sin
  pendientes locales. Permanece `axes.W006` previamente silenciado. Archivos en UTF-8 y CRLF.
- Migraciones `compras/0002–0003` y `parametros/0010` aplicadas a SQLite tras el respaldo
  `C:/Users/USUARIO/AppData/Local/Temp/suministros-respaldos/db-antes-b5-20261111-115431.sqlite3`.
- Se conserva `.env` y la base PostgreSQL habitual. No se crearon commits ni push.

Siguiente etapa: **B6, puestos y decisión en la lista de elegibles**.

## 2026-11-11 · B4: necesidades y listas de elegibles FR-GDS-20

- Nueva app `compras`, preparada para reunir elegibles y los futuros módulos de
  cotizaciones, órdenes y seguimiento. Reutiliza proveedores y proyecciones.
- Necesidad con objeto, área activa, fecha, responsable, estado abierto y origen
  manual por texto/tipo configurable o líneas de proyección aprobadas. Catálogo
  de orígenes administrable, desactivable y sin datos oficiales inventados.
- Relación intermedia con cantidad Decimal positiva por línea, hasta tres decimales,
  que permite agrupar y dividir. Se rechazan líneas repetidas, no aprobadas, de otra
  área e inexistentes, sin conservar escrituras parciales. Filtro por área y periodo.
- Foto de producto, unidad, periodo y cantidad autorizada vigente por origen. Los
  ajustes posteriores no reescriben esos datos. No se suman unidades diferentes.
  D-09 sigue pendiente: no se inventan reservas, consumos ni topes entre necesidades.
- Listas en borrador con necesidad, fecha y creador. Participantes únicos por
  proveedor y por NIT, con identidad y razón social conservadas aunque cambie la
  ficha. Se rechazan proveedores inactivos y cambios sobre listas cerradas/anuladas.
- Retiro con motivo sin borrado; reactivar conserva la fila y su identidad original.
  El servidor bloquea la lista durante los cambios para serializar altas y retiros.
- Acceso desde Compras; tipos también enlazados en Configuración. Vistas y servicios
  limitados a Administrador/Desarrollador, formularios CSRF y bitácora transaccional
  de cada acción. Modelos en solo lectura dentro del administrador técnico.
- Guía de uso y límites en `docs/necesidades_elegibles.md`. Calificación, decisión,
  vínculo documental y cierre se implementarán en B5–B8.

### Verificación

- Suite SQLite: **566 pruebas sin fallos**, con una prueba exclusiva de concurrencia
  PostgreSQL omitida. Dieciséis pruebas nuevas sobre las 550 de B3.
- Suite PostgreSQL 18.6: **566 pruebas correctas** en base temporal aislada, con
  Python 3.13.15 y Django 5.2.19. La base temporal se eliminó al terminar.
- `check` sin errores, `makemigrations --check` sin cambios y `migrate --check` sin
  pendientes locales. Permanece el aviso `axes.W006` previamente silenciado.
- Sintaxis JavaScript comprobada con `node --check`. Archivos editados en UTF-8 y CRLF.
- Migración `compras/0001_initial` aplicada a SQLite tras el respaldo
  `C:/Users/USUARIO/AppData/Local/Temp/suministros-respaldos/db-antes-b4-20261111-113832.sqlite3`.
- Se conserva `.env` y la base PostgreSQL habitual. No se crearon commits ni push.

Siguiente etapa: **B5, criterios versionados y calificación ponderada de elegibles**.

## 2026-11-11 · B3: documentos exigidos y vigencias por requisito

- `DocumentoExigido`: categoría, tipo, requisito opcional, obligatoriedad y activo,
  con unicidad de las asociaciones y controles de pertenencia a la categoría.
  Pantallas de configuración reutilizan los permisos, motivos y bitácora existentes.
- Migración de datos intencionalmente vacía para D-05: **no se inventan documentos
  obligatorios oficiales**. La clínica debe confirmar y configurar su lista.
- Servicio de clasificación y tablero con fecha fija inyectable: vigente, próximo,
  vencido y faltante. Ignora expediciones posteriores a la referencia y detecta
  la falta de vencimiento obligatorio. Selecciona el documento más reciente expedido
  a la fecha; usa plazo general (30) o particular del tipo. Referencia por defecto
  `timezone.localdate()` en America/Bogota.
- Tableros en ficha y evaluación; solo vencidos/faltantes usan rojo. El de la
  evaluación usa categoría/versión guardadas y su fecha. Se distingue el catálogo
  documental actual de los controles históricos conservados en las respuestas.
- Selector de evidencia con estado a fecha de evaluación. Responder Sí guarda
  estado, fecha, plazo, exigencias aplicadas, advertencias y modo D-05. Un documento
  antiguo vencido sigue apareciendo vencido aunque exista una renovación vigente.
- Parámetro `evaluacion.bloquear_si_documento_vencido`: No por defecto, permite con
  advertencia. Sí bloquea nueva respuesta Sí con evidencia vencida/no expedida o sin
  vencimiento obligatorio, y bloquea copiar esas respuestas a otro borrador.
  Faltantes sin evidencia generan advertencia; no se impone un bloqueo no aprobado.
- Controles documentales de respuestas finalizadas no se modifican al renovar
  documentos o cambiar parámetros. Para respuestas anteriores a B3 se muestra la
  limitación del plazo general actual sobre las fechas documentales conservadas.
- Vencimientos filtrable por NIT/nombre, categoría, tipo y estado. Catálogos y
  consultas internas conservan permisos administrativos; los PDF siguen privados.
- Guía en `docs/control_documental.md`. Las exigencias vinculadas a requisitos de
  nuevas versiones se configuran expresamente; no se duplican obligaciones oficiales.

### Verificación

- Suite SQLite: **550 pruebas sin fallos**, con una prueba exclusiva de concurrencia
  PostgreSQL omitida. Doce pruebas nuevas sobre las 538 de B2.
- Suite PostgreSQL 18.6: **550 pruebas correctas**, con Python 3.13.15 y Django 5.2.19,
  en base temporal aislada, más comprobaciones focalizadas del control documental.
- `check` sin errores y `makemigrations --check` sin cambios. `migrate --check`
  sin pendientes locales. Permanece el aviso `axes.W006` previamente silenciado.
- Migraciones `proveedores/0010–0011`, `parametros/0008` y aclaración de descripción
  `parametros/0009` aplicadas a SQLite tras el respaldo
  `C:/Users/USUARIO/AppData/Local/Temp/suministros-respaldos/db-antes-b3-20261111-112129.sqlite3`.
  La aclaración no cambia el valor configurado del parámetro.
- No se modificó `.env` ni la base PostgreSQL habitual; no se crearon commits ni push.

Siguiente etapa: **B4, necesidades y listas de elegibles FR-GDS-20**.

## 2026-11-11 · B2: historial, anulación y copia de evaluaciones

- Historial en la ficha del proveedor con las diez más recientes y listado
  completo paginado: fecha, versión de matriz, evaluador, porcentaje, calificación,
  estado y enlace al detalle. Se mantiene visible que D-06 puede ser provisional.
- `Proveedor.evaluacion_vigente`: última finalizada no anulada, ordenada por fecha
  de finalización e ID. Finalizar una nueva cambia la vigente; anularla recupera
  la anterior. Los borradores y copias no cambian esa selección.
- Anulación de borrador/finalizada con motivo, responsable, fecha y bitácora.
  No borra respuestas ni PDF; una finalizada conserva exactamente sus resultados
  y fechas originales. Un borrador anulado conserva su cálculo parcial al anular.
  Repetir la anulación se rechaza y los estados de solo lectura no admiten edición.
- Copia a un borrador nuevo con vínculo al origen, conservando proveedor, categoría,
  versión y fecha del origen. Permite copiar respuestas/evidencias o comenzar vacío.
  Para otra fecha/categoría/matriz se utiliza la creación de una evaluación nueva.
  La copia no hereda resultados finales ni información de anulación y se recalcula
  con parámetros D-06 actuales. Las correcciones no afectan al origen.
- Los PDF se comparten mediante registros de adjuntos propios de cada evaluación,
  sin escribir copias en disco. Las fotos de documentos se conservan; los adjuntos
  históricos no usados por respuestas actuales siguen consultables en el origen.
- Rutas con `rol_requerido`, POST con CSRF en anulación/copia y motivo obligatorio.
  Servicios transaccionales con bloqueo del origen y reversión de cambios si falla
  la auditoría. El formulario de respuesta devuelve 403 para finalizadas/anuladas.
- Restricciones de estado y metadatos de anulación también en la base de datos.
- Guía de uso en `docs/historial_evaluaciones.md`.

### Verificación

- SQLite: **538 pruebas sin fallos**, con una prueba exclusiva de concurrencia
  PostgreSQL omitida. Se agregaron 12 pruebas a las 526 anteriores.
- PostgreSQL 18.6: **538 pruebas correctas**, con Python 3.13.15 y Django 5.2.19,
  en una base temporal aislada eliminada al terminar.
- `check` sin errores; `makemigrations --check` sin cambios; `migrate --check`
  sin pendientes locales. Permanece el aviso `axes.W006` previamente silenciado.
- Migración `proveedores/0009` aplicada a SQLite después del respaldo
  `C:/Users/USUARIO/AppData/Local/Temp/suministros-respaldos/db-antes-b2-20261111-111140.sqlite3`.
- No se modificó `.env` ni la base PostgreSQL habitual. No se crearon commits ni push.

Siguiente etapa: **B3, documentos exigidos por categoría y vigencias asociadas a requisitos**.

## 2026-11-11 · B1: cálculo de evaluación FR-GDS-14

- Función pura `proveedores/evaluacion.py`: calcula puntos por requisito, máximo
  aplicable, porcentaje, calificación 1/3/5 y desglose por grupo, usando exclusivamente
  `Decimal` y redondeo `ROUND_HALF_UP` a dos decimales. No modifica la entrada.
- El servicio construye la entrada desde los pesos de la versión fija de la
  evaluación. No utiliza la matriz vigente al día de consulta.
- D-06 `evaluacion.reglas_calculo`: reglas JSON coherentes, editables con motivo
  desde Configuración. Inicialmente Sí=peso, No=0, N/A excluido, umbral de nota 3
  en 60 % y de nota 5 en 80 %. **Son valores provisionales, no aprobados por la clínica**;
  la interfaz muestra su condición pendiente. Se validan rangos, tipos y orden
  de umbrales antes de guardar.
- Resultado provisional y desglose visibles en el detalle, incluyendo respuestas
  pendientes y el caso «No calculable» con máximo cero. Una evaluación incompleta
  o sin máximo aplicable no puede finalizarse.
- Finalización por POST con motivo y permisos administrativos, bloqueando evaluación
  y reglas mientras se guarda la foto de resultados, parámetros, desglose, responsable
  y fecha. Cambiar reglas o publicar otra matriz no altera la foto finalizada.
- Respuestas y adjuntos finalizados quedan en solo lectura. Un fallo de auditoría
  revierte la finalización. No se incorporan todavía anulación ni copia (B2).
- Pruebas de todo Sí/No, mezcla N/A, todo N/A, pesos 1/2, reglas alternativas,
  redondeo, umbrales, configuración inválida, fotografía histórica y permisos.
  El caso fijo «hoja validada» es provisional y está marcado para reemplazar o
  complementar cuando negocio entregue su hoja oficial; no se afirma aprobación clínica.
- Guía de uso y configuración en `docs/calculo_fr14.md`.

### Verificación

- SQLite: **526 pruebas sin fallos**, con una prueba exclusiva de concurrencia
  PostgreSQL omitida. Diez pruebas nuevas sobre las 516 anteriores.
- PostgreSQL 18.6: **526 pruebas correctas**, con Python 3.13.15 y Django 5.2.19,
  en una base temporal aislada eliminada al terminar.
- `check` sin errores; `makemigrations --check` sin cambios; `migrate --check`
  sin pendientes locales. Permanece el aviso `axes.W006` previamente silenciado.
- Migraciones `parametros/0007` y `proveedores/0008` aplicadas a SQLite tras respaldo
  `C:/Users/USUARIO/AppData/Local/Temp/suministros-respaldos/db-antes-b1-20261111-105949.sqlite3`.
- No se modificó `.env` ni la base PostgreSQL habitual. No se crearon commits ni push.

Siguiente etapa: **B2, historial, anulación, copia y evaluación vigente**.

## 2026-11-11 · A17: respuestas y evidencias FR-GDS-14

- `RespuestaEvaluacion`: única por evaluación/requisito, SI/NO/N/A, observación,
  confirmación explícita de N/A, documento opcional, PDF opcional, responsable y fecha.
  Las restricciones de unicidad, valores válidos y confirmación de N/A también
  se aplican en la base de datos.
- Servicio transaccional que bloquea la evaluación y valida borrador, versión,
  categoría y proveedor del documento. Cada creación/corrección guarda actor,
  motivo, fecha y valores anterior/nuevo en bitácora.
- `EvidenciaEvaluacion`: adjuntos privados con nombre UUID, PDF validado de hasta
  10 MB y vínculo fijo a la evaluación. Reemplazar/desvincular conserva los PDF
  anteriores como adjuntos históricos; no hay edición ni borrado desde la interfaz.
- La respuesta guarda una foto de los datos del documento usado como respaldo.
  El borrado de archivos respeta esas referencias y su bitácora: reemplazar un
  documento de ficha no destruye el PDF que respalda respuestas anteriores.
  Los documentos vinculados se protegen frente a borrado.
- Formulario por requisito, con confirmación y observación para N/A, documento
  filtrado al proveedor y/o PDF propio. El detalle agrupa Calidad, Ambiental y
  SG-SST, muestra pesos, avance, responsables, fechas, evidencias y adjuntos históricos.
  Las evaluaciones se abren también desde la ficha del proveedor.
- Descargas de PDF propio y documental con rol administrativo, alcance por
  evaluación, adjunto, `nosniff` y `private, no-store`. Coordinadores y proveedores
  reciben 403; cambiar el ID de evaluación de un adjunto devuelve 404.
- Las cargas fallidas revierten respuesta/adjunto y limpian el PDF nuevo. Se
  rechazan cargas dentro de transacciones externas. Admin técnico solo lectura.
- Guía en `docs/respuestas_fr14.md`. No se calcula todavía la calificación ni se
  finaliza la evaluación: cálculo D-06 en B1 e historial de finalización en B2.

### Verificación

- Suite SQLite: **516 pruebas sin fallos**, con una prueba de concurrencia
  exclusiva de PostgreSQL omitida. Se agregaron 14 pruebas sobre las 502 anteriores.
- `check` sin errores; `makemigrations --check` sin cambios; `migrate --check`
  sin pendientes locales. Permanece el aviso `axes.W006` previamente silenciado.
- Migración `proveedores/0007` aplicada en SQLite después del respaldo
  `C:/Users/USUARIO/AppData/Local/Temp/suministros-respaldos/db-antes-a17-20261111-105130.sqlite3`.
- Suite PostgreSQL 18.6: **516 pruebas correctas** con Python 3.13.15 y Django
  5.2.19, en una base temporal aislada eliminada al terminar. No se modificó `.env` ni la base PostgreSQL habitual,
  ni se crearon commits ni se hizo push.

Siguiente etapa: **B1, cálculo de puntos, porcentaje y calificación configurable**.

## 2026-11-11 · A16: versiones de matriz FR-GDS-14

- `VersionMatriz`: número, estado borrador/publicada/retirada, vigencia y notas.
  El catálogo anterior se migra a la versión 1 en borrador sin cambiar sus IDs.
  No se publican automáticamente datos de ejemplo ni textos sin validar.
- `Requisito` pertenece a una versión y su número es único dentro de ella; los
  pesos pertenecen a esa misma versión a través del requisito, sin un FK redundante.
- Copia auditada de requisitos y pesos a un borrador nuevo. Publicación con fechas
  sin solapamiento y pesos completos para las categorías incluidas. Una sucesora
  cierra el intervalo abierto anterior el día previo; la versión anterior conserva
  sus datos y es aplicable a fechas de su intervalo.
- Contenido publicado o retirado bloqueado en modelos, servicios y operaciones de
  actualización/borrado del queryset. Numeración y publicación usan un cerrojo
  transaccional común. El admin técnico de matrices y evaluaciones es solo lectura.
- `EvaluacionProveedor`: conserva proveedor, categoría, nombre de categoría,
  versión, fecha, evaluador y estado borrador. La publicación de otra versión
  no cambia su contenido. No se permite reasignar su identidad.
- Vistas administrativas de matrices, publicación/copia por POST con motivo,
  nueva evaluación desde la ficha (categoría propuesta), vista previa y detalle.
  Todos los accesos tienen `rol_requerido`; coordinadores y proveedores reciben 403.
- Configuración permite seleccionar y filtrar por versión. La carga CSV acepta
  `--matriz N` (predeterminada 1) y rechaza versiones publicadas o retiradas.
- Guía en `docs/matrices_fr14.md`. A17 añadirá respuestas y evidencias; A16 no
  calcula ni presenta una calificación provisional.

### Verificación

- Suite SQLite: 502 pruebas sin fallos, con una prueba de concurrencia exclusiva
  de PostgreSQL omitida. Se agregaron seis pruebas sobre las 496 anteriores.
- Prueba adicional de migración en una base temporal: partiendo del esquema A15
  con requisito y peso ficticios, se verificó que sus IDs, texto y valor quedan
  intactos en versión 1 después de aplicar A16.
- `check` sin errores y `makemigrations --check` sin cambios. Migración
  `proveedores/0006` aplicada en SQLite tras el respaldo
  `C:/Users/USUARIO/AppData/Local/Temp/suministros-respaldos/db-antes-a16-20261111-103043.sqlite3`.
- Suite PostgreSQL 18.6: **502 pruebas correctas**, con Python 3.13.15 y Django
  5.2.19, en una base temporal aislada eliminada al terminar. No se modificó `.env`, ni la base PostgreSQL habitual,
  ni se crearon commits o push.

Siguiente etapa: **A17, respuestas SI/NO/N/A y evidencias de cada evaluación**.

## 2026-11-10 · A15 completo: bandeja de revisión de envíos

### Implementado

- `/proveedores/bandeja/`, solo para administradores y desarrolladores: pendientes
  por defecto, filtros combinables por proveedor, NIT/nombre, tipo, fechas y estado,
  paginación y consulta del historial. Acceso desde el submenú y desde cada ficha.
- Detalle y descarga privada del PDF, con adjunto, `nosniff` y `private, no-store`.
  Todas las rutas internas usan `rol_requerido`; revisar admite únicamente POST con CSRF.
- Aceptación transaccional con bloqueo del envío: crea `DocumentoProveedor` con
  los datos del envío, **reutiliza la misma ruta y el mismo PDF**, guarda el vínculo
  único al documento, responsable, fecha y motivo. Un envío revisado no admite otra decisión.
- Descarte con motivo obligatorio y bitácora. Parámetro editable
  `proveedor.conservar_pdf_descartado`, Sí por defecto. Si se elige No, se quita
  la referencia al PDF y se programa el borrado después del commit solo cuando
  no tiene otras referencias. Un rollback conserva registro y archivo anteriores.
  El historial y el nombre original del archivo siempre se conservan.
- Carga manual de documentos recibidos por otros medios, con proveedor, tipo,
  fechas, PDF, motivo y responsable administrativo. Queda pendiente de revisión.
  Portal y bandeja usan un único servicio de creación, con transacción durable,
  validación de PDF y limpieza del archivo si falla la operación.
- Restricciones de base de datos: pendiente/aceptado requiere PDF y un envío
  aceptado requiere su documento; otros estados no pueden tener ese vínculo.
  El documento aceptado se protege contra eliminación que rompa el historial.
- Documentación de uso y política de retención en `docs/bandeja_envios.md`.

### Verificación

- Suite SQLite: **496 pruebas, sin fallos; una omitida** porque verifica bloqueos
  concurrentes exclusivos de PostgreSQL.
- Suite PostgreSQL 18.6: **496 pruebas correctas**, con Python 3.13.15 y Django
  5.2.19. Incluye dos conexiones intentando aceptar el mismo envío: solo se crea
  un documento. Se agregaron 18 pruebas a las 478 de la entrega anterior.
- `check`: sin errores; `makemigrations --check`: sin cambios; `migrate --check`:
  sin migraciones locales pendientes. Permanece el aviso `axes.W006` previamente silenciado.
- `parametros/0006` y `proveedores/0005` aplicadas a SQLite después del respaldo
  `C:/Users/USUARIO/AppData/Local/Temp/suministros-respaldos/db-antes-a15-20261110-161128.sqlite3`.
- No se modificó `.env` ni la base PostgreSQL habitual; las verificaciones usan
  bases PostgreSQL temporales con nombres únicos. No se crearon cuentas ficticias
  en la base local, commits ni push. Mensaje sugerido:
  `Implementar bandeja de revisión y retención de envíos de proveedores`.

### Siguiente paso

- **A16: versiones de la matriz FR-GDS-14 y evaluación por categoría y versión.**
- La clínica debe confirmar la política de retención. El parámetro afecta a los
  descartes nuevos; no borra archivos de descartes anteriores al cambiarlo.

## 2026-11-10 · A14 completo: portal de proveedores

### Implementado

- Registro público en `/portal/registro/`, con NIT canónico, razón social, tipo
  de persona, contacto, dirección, correo y contraseña validada. Crea ficha
  «Registrado» y usuario proveedor vinculado, sin área ni privilegios internos.
  Alta y cuenta quedan auditadas con actor, fecha y motivo, sin guardar contraseñas
  en bitácora. Una falla revierte ficha y usuario juntos.
- NIT y correos duplicados reciben la misma respuesta genérica que una solicitud
  nueva; no se revelan fichas ni se crean usuarios sobre proveedores existentes.
- Parámetro D-03 `portal.activar_cuenta_al_registrar`, Sí por defecto, editable
  en Configuración. No deja la cuenta inactiva para activación administrativa.
  Activar la cuenta no aprueba al proveedor y no inicia una sesión automáticamente.
- Protección del registro: CSRF, campo trampa, límite de 5 intentos por IP en 900
  segundos, configurable desde el entorno. El contador en caché abarca sesiones
  distintas y devuelve 429 con `Retry-After`. No confía en encabezados de proxy
  arbitrarios ni conserva la IP en texto claro en las claves de caché.
- `/portal/`: ficha propia en solo lectura, documentos propios con vigencia y
  listado paginado de envíos, estados y observaciones. Un proveedor inactivo
  conserva la consulta histórica y no puede presentar nuevos envíos.
- `EnvioProveedor` en la app proveedores, sin modelos en portal: proveedor,
  tipo, fechas, PDF privado, autor, estado pendiente/aceptado/descartado, revisión
  y motivo. Restricciones de estado, fechas y coherencia de revisión en la base.
- Enviar PDF en `/portal/envios/nuevo/`: extensión, cabecera y 10 MB con la
  utilidad existente; almacena `envios/AAAA/MM/<uuid>.pdf`. Siempre nace pendiente
  y no crea un documento oficial. No hay pantallas de edición ni borrado del envío.
- Descargas propias de envíos y documentos en vistas separadas del portal, con
  `rol_requerido`, alcance por `request.user.proveedor`, adjunto, `nosniff` y
  `private, no-store`. Un ID ajeno devuelve 404; roles internos reciben 403.
  Las vistas administrativas de proveedores mantienen sus restricciones.
- Las cargas usan transacción durable y eliminan el PDF nuevo si falla el guardado.
  Al borrar un envío o documento, el archivo se elimina después del commit solo
  si no tiene otras referencias; esto permite reutilizar un PDF al aceptar en A15.
- Admin técnico de envíos en solo lectura, sin enlace público al archivo.
- Enlace de registro en el ingreso y guía en `docs/portal_proveedores.md`.

### Verificación y migraciones

- **478 pruebas correctas en SQLite y 478 en PostgreSQL 18.6**, con Python 3.13.15
  y Django 5.2.19 (26 pruebas nuevas). PostgreSQL se verificó en una base aislada
  con nombre único, eliminada por el ejecutor al terminar.
- `check`: sin errores (permanece el aviso `axes.W006` previamente silenciado).
- `makemigrations --check`: sin cambios. `migrate --check`: sin pendientes locales.
- Migraciones `parametros/0005` y `proveedores/0004` aplicadas a la base local
  SQLite después de crear el respaldo
  `C:/Users/USUARIO/AppData/Local/Temp/suministros-respaldos/db-antes-a14-20261110-155010.sqlite3`.
- Comprobación sobre la base local: registro público responde 200 y el portal
  privado sin sesión redirige al ingreso. No se crearon usuarios de ejemplo en ella.
- No se modificó `.env`, no se hicieron commits ni push. Mensaje sugerido:
  `Implementar registro y documentos privados del portal de proveedores`.

### Siguiente paso

- **A15: bandeja administrativa** para revisar, aceptar reutilizando el PDF,
  descartar con motivo y cargar envíos manuales. Hasta entonces los nuevos envíos
  permanecen pendientes.
- Antes de publicación en internet: captcha, verificación de correo, HTTPS y
  caché compartida entre procesos, conforme a A14. La protección actual es básica;
  la caché local de desarrollo no coordina varios procesos. Véase la guía del portal.

## 2026-11-10 · Revisión de lo existente y A12 completo

### Pendientes cerrados de módulos existentes

- A11: se valida el XML de la hoja antes de leer sus celdas. Una dimensión falsa
  como `A1:A1` ya no oculta filas ni evita los límites de filas/columnas.
- A10: revisión muestra costo original y costo vigente por proyección y los
  totales del filtro, reutilizando el cálculo del consolidado. Los textos que
  comienzan con `=` se exportan como texto en Excel, sin ejecutar fórmulas.
- Índice `Ajuste(linea, campo, -fecha, -id)` para buscar los valores vigentes.
- A13: los servicios rechazan actores inactivos. Una carga de PDF nueva exige
  una transacción durable propia y rechaza una transacción externa antes de
  escribir el archivo; se cierra el caso conocido de rollback externo con PDF huérfano.
- Plantillas 404 y 500 en español. La página 500 no consulta la base de datos.
- Los filtros muestran los errores de validación junto a sus campos.

### A12 · Catálogo FR-GDS-14

- Se reutilizan `CategoriaProveedor` y `TipoDocumento`; se agregan descripción,
  días de alerta por tipo (30 por defecto) y selección del plazo general o propio.
  Los tipos existentes siguen usando el parámetro general, conservando su comportamiento.
- Modelos `Requisito` (número único positivo, grupo Calidad/Ambiental/SG-SST,
  texto y activo) y `Peso` (requisito/categoría únicos, valor 1 o 2).
  Las restricciones también se aplican en la base de datos; relaciones `PROTECT`.
- Configuración → Catálogos de proveedores: listados con filtros y paginación,
  crear/editar, activar/desactivar con motivo; los pesos se editan conservando
  la pareja requisito/categoría. Permisos administrativos en todas las rutas
  y servicios, con actor, fecha, motivo y valores anterior/nuevo en bitácora.
- Comando `cargar_fr14`: CSV UTF-8 de hasta 2 MB y 5000 filas; exige un actor
  administrativo activo y motivo. Valida todo antes de guardar y revierte toda
  la carga si falla. Repetir un archivo no duplica datos ni historial. No borra
  registros ausentes ni reactiva catálogos desactivados.
- `docs/ejemplos/fr14_ejemplo.csv`: 26 requisitos y 52 pesos ficticios. No se
  cargan automáticamente en la base local. Guía en `docs/ejemplos/fr14_csv.md`.
- Migraciones nuevas: `proveedores/0003` y `proyecciones/0005`, aplicadas en SQLite
  después del respaldo
  `C:/Users/USUARIO/AppData/Local/Temp/suministros-respaldos/db-antes-a12-20261110-153515.sqlite3`.

### Verificación

- Entorno `.venv` creado con Python 3.13.15 y las dependencias fijadas del proyecto.
- `check`: sin errores; `makemigrations --check`: sin cambios; `migrate --check`:
  sin migraciones pendientes en la base local SQLite.
- **452 pruebas correctas en SQLite y 452 en PostgreSQL 18.6**, ambas con
  Python 3.13.15 y Django 5.2.19 (30 pruebas agregadas sobre las 422 anteriores).
- Para PostgreSQL se usó `PSYCOPG_IMPL=python` y `libpq` de la instalación nativa,
  evitando la DLL binaria que bloquea Windows. Se corrigió la migración de
  bitácora para que el `%` literal del disparador no se interprete como parámetro.
- La suite PostgreSQL creó una base temporal con nombre único y aplicó allí todas
  las migraciones. No se migró ni modificó la base PostgreSQL habitual. Las bases
  temporales se limpiaron al terminar, incluida la del primer intento fallido.
- No se modificó `.env`, no se cargaron datos ficticios en la base habitual y
  no se crearon commits ni se hizo push.

### Lo que sigue

- A12 está terminado técnicamente. Los textos y pesos oficiales deben entregarse
  y aprobarse por la clínica antes de cargarlos.
- A13 ya existía y fue revisado. La próxima etapa funcional es **A14: portal de
  proveedores**, seguida de A15 (bandeja) y A16–A17 (evaluaciones).
- Las decisiones de negocio pendientes y los módulos futuros no se dan por
  resueltos mediante supuestos. El mapa completo está en `docs/estado_prompts.md`.

## 2026-11-10 · Revisión de hoja de ruta y A11: importación desde Excel

### Estado actual

- Se revisaron los 45 prompts y el código existente. El detalle está en
  [estado_prompts.md](estado_prompts.md). El proyecto había avanzado por A1–A10 y A13,
  dejando pendientes A11 y buena parte de A12. La siguiente tarea es completar A12.
- Esta sección actualiza el estado vigente; los registros anteriores se conservan
  como historial, incluidos sus problemas de ejecución ya resueltos para SQLite.

### Implementado

- `/proyecciones/plantilla-excel/`: plantilla con encabezados, instrucciones,
  catálogo de unidades activas y validación de selección.
- `/proyecciones/<id>/importar/`: carga `.xlsx`, vista previa por fila y confirmación.
  Límite técnico: 10 MB, 1000 líneas y 50 MB descomprimidos; rechaza fórmulas,
  macros, archivos dañados, columnas equivocadas, cantidades inválidas y precios
  que exceden los límites del modelo. Montos oficiales con `Decimal`.
- La vista previa se guarda en la sesión de base de datos del servidor, ligada
  al actor y a la proyección, con token y vigencia de 30 minutos. El navegador no
  envía las líneas que se guardarán. No se conserva el Excel en disco.
- Confirmación en `servicios.py`, con transacción, bloqueos del periodo y la
  proyección, validación actual de unidades y huella de las líneas para detectar
  cambios desde la vista previa. Una repetición no vuelve a agregar las filas.
- Puede agregar o reemplazar únicamente con filas válidas; reemplazar sin filas
  válidas no borra nada. Se informa cuáles quedaron excluidas. Las eliminaciones,
  creaciones y el resumen de importación conservan actor, motivo y valores en bitácora.
- Coordinadores: solo su borrador en periodo abierto. Administración: proyecciones
  no aprobadas; si hay aprobaciones parciales debe devolver primero la proyección.
  Una aprobada conserva sus valores y solo admite el mecanismo existente de ajustes.
- Accesos a la carga desde la proyección del coordinador y el detalle de revisión.

### Compatibilidad y entorno local

- Se encontró SQLite activo en settings, aunque el disparador de bitácora y el
  consolidado todavía contenían SQL exclusivo de PostgreSQL. La suite ni siquiera
  podía crear su base de pruebas.
- La migración `bitacora/0002` ahora crea disparadores de solo inserción según el
  motor; PostgreSQL conserva su SQL. El consolidado extrae JSON con la función de
  SQLite cuando corresponde. No se desactivó la protección del historial para probar.
- `DJANGO_BASE_DATOS` selecciona `sqlite` o `postgresql`; conserva SQLite local por
  defecto y PostgreSQL en producción. Las credenciales se exigen al elegir PostgreSQL.
  `.env.example` y README documentan la elección. No se modificó `.env`.
- Antes de aplicar las migraciones locales pendientes se creó un respaldo de
  `db.sqlite3` mediante la API de copia de SQLite, en
  `C:/Users/USUARIO/AppData/Local/Temp/suministros-respaldos/db-antes-migraciones-20261110-151349.sqlite3`.
  Las migraciones se aplicaron correctamente, sin recrear la base.
- No se crearon commits: todos los archivos del proyecto ya estaban sin rastrear.
  Mensaje sugerido: `Completar importación de proyecciones desde Excel`.

### Verificación

- `python manage.py check`: sin errores (aviso `axes.W006` previamente silenciado).
- `python manage.py makemigrations --check`: sin cambios de modelos.
- `python manage.py test --noinput`: **422 pruebas correctas** en SQLite con
  Python 3.12.10 y Django 5.2.19 (398 existentes y 24 agregadas).
- `python manage.py migrate --check`: sin migraciones pendientes en la base local.
- Pendiente: ejecutar la suite con Python 3.13 y PostgreSQL 18; no se da por validado
  ese entorno solo por haber conservado su SQL.

## 2026-11-05 · Tarea 1: esqueleto del proyecto

### Hecho

- Proyecto Django `config` (settings, urls, wsgi, asgi) y `manage.py` en la raíz.
- `requirements.txt` con versiones fijas: Django 5.2.19, psycopg[binary] 3.3.8,
  django-axes 9.0.0, openpyxl 3.1.5, python-dotenv 1.2.4.
- Configuración leída de `.env` con python-dotenv. Las funciones de conversión
  (texto, obligatoria, booleano, entero, lista por comas) están en `config/entorno.py`.
  - `DJANGO_SECRET_KEY` y `POSTGRES_DB/USER/PASSWORD` son obligatorias, sin valor por defecto.
  - `DJANGO_DEBUG` es False por defecto. `POSTGRES_HOST` es 127.0.0.1 (ver tarea 2) y `POSTGRES_PORT` es 5433.
  - `DJANGO_PRODUCCION=True` activa SSL redirect, cookies seguras, HSTS configurable,
    `SECURE_PROXY_SSL_HEADER` (solo con `DJANGO_DETRAS_DE_PROXY=True`) y `CSRF_TRUSTED_ORIGINS`
    (solo https). Rechaza `DEBUG=True` y `ALLOWED_HOSTS` vacío.
- es-co, America/Bogota, USE_TZ. `MEDIA_ROOT = archivos_privados/` sin `MEDIA_URL` ni ruta pública.
  `STATICFILES_DIRS = static/`, `STATIC_ROOT = staticfiles/`.
- django-axes instalado como app, middleware y backend: 5 intentos fallidos por
  usuario + IP y bloqueo de 30 minutos. Con `DJANGO_DETRAS_DE_PROXY=True`, la IP del cliente
  se toma de X-Forwarded-For (`config/seguridad.py`).
- Sin `LocaleMiddleware`: la interfaz queda siempre en es-co, sin importar el idioma del navegador.
- `docker-compose.yml`: postgres:18, `127.0.0.1:${POSTGRES_PORT:-5433}:5432`, volumen
  `datos_postgres` montado en `/var/lib/postgresql` (ruta que usa PostgreSQL 18) y healthcheck.
- `.env.example`, `.gitignore` y `.gitattributes` (CRLF para el texto, binario para pdf/xlsx/png/jpg).
- `templates/base.html` con encabezado, bloque de menú por rol (vacío), mensajes y pie.
  `static/css/estilos.css` con las variables de color.
- `README.md` con la instalación en Windows.
- Pruebas en `config/tests.py`: lectura del entorno, settings por defecto y de
  producción, idioma y zona horaria, ausencia de URL pública para archivos privados
  (también con DEBUG=True), axes e IP detrás de proxy, plantilla base, colores y la regla
  de etiquetas `{% %}` en una sola línea.
- Revisión adversarial con 3 revisores independientes: se corrigieron 7 hallazgos (IP del
  cliente en axes detrás de proxy, idioma forzado a es-co, advertencia sobre `$` en la
  contraseña, roles ARIA de los mensajes, prueba de MEDIA sin depender de DEBUG, foco visible
  sobre fondo azul y el texto de este registro).

### Verificado

- `python manage.py check`: sin errores.
- `python manage.py makemigrations --check`: sin cambios.
- `python manage.py test`: 21 pruebas OK.
- `python manage.py check --deploy` con `DJANGO_PRODUCCION=True` y los valores por defecto:
  quedan los avisos W005 (HSTS en subdominios) y W021 (precarga HSTS). Son intencionales;
  se activan con `DJANGO_HSTS_SUBDOMINIOS` y `DJANGO_HSTS_PRELOAD` cuando se confirme que
  todo el dominio funciona por HTTPS.
- `docker compose up` levanta PostgreSQL 18.6 sano y Django se conecta. Se probó en un
  proyecto temporal en el puerto 5434, que luego se eliminó.
- **No se ha ejecutado `migrate`**, a propósito.

## 2026-11-05 · Tarea 2: áreas, usuario propio y roles

### Hecho

- App `areas`, modelo `Area`:
  - Campos: `nombre`, `codigo_area`, `activa` y `fecha_creacion`.
  - Unicidad sin distinguir mayúsculas: índice único sobre `LOWER(nombre)` para el nombre; el código se guarda siempre en mayúsculas.
  - Se normalizan los espacios del nombre.
  - En el admin no se pueden borrar; se desactivan.
- App `cuentas`, modelo `Usuario` (AbstractBaseUser + PermissionsMixin):
  - Campos: `correo` (USERNAME_FIELD, guardado en minúsculas), `nombre`, `activo`, `is_staff`, `rol`,
    `area` (FK opcional con `on_delete=PROTECT`), `debe_cambiar_clave` y `fecha_creacion`.
  - `is_active` es una propiedad sobre `activo`, para que el login de Django y django-axes respeten
    a los usuarios desactivados.
  - `UsuarioManager`: `create_user` valida con `full_clean()`; `create_superuser` deja el rol
    desarrollador; `get_by_natural_key` no distingue mayúsculas.
  - `AUTH_USER_MODEL = "cuentas.Usuario"` se activó antes del primer `migrate`.
- Reglas de rol, validadas en `clean()` y también en PostgreSQL con `CheckConstraint`, para que se cumplan aunque se use `.update()`:
  - el coordinador tiene área obligatoria;
  - el proveedor no tiene área;
  - el rol debe ser uno de los 4 válidos;
  - solo los desarrolladores pueden tener `is_staff` o `is_superuser`;
  - el correo se guarda siempre en minúsculas (`CHECK correo = LOWER(correo)`), así que `unique`
    lo hace único sin distinguir mayúsculas, y el código de área va siempre en mayúsculas
    (`CHECK codigo_area = UPPER(codigo_area)`).
- `cuentas/permisos.py`:
  - `rol_requerido(*roles)`: sin sesión, redirige al login con `?next=`; con un rol no permitido o un usuario inactivo, devuelve 403.
    Falla al definir la vista si no recibe roles o si recibe un rol desconocido.
  - `es_admin(usuario)`.
  - Constante `ROLES_ADMIN` en `cuentas/models.py`.
- Vistas:
  - `cuentas:ingresar`: LoginView con plantilla y mensajes en español; no sigue `next` hacia sitios externos.
  - `cuentas:salir`: solo POST.
  - `inicio`: todos los roles.
  - `templates/403.html` y `templates/cuentas/bloqueado.html` (bloqueo de axes, HTTP 429).
- django-axes cuenta los intentos por correo normalizado (`cuentas/seguridad.py`), así que
  cambiar mayúsculas no evade el bloqueo.
- Admin de Usuario (alta con doble contraseña, edición, cambio de clave, sin grupos ni borrado) y de Area.
- El admin de Django es el administrador técnico, exclusivo de **desarrolladores superusuarios activos**
  (`config/admin_sitio.py`, registrado con `config.apps.AdminTecnicoConfig`). Los administradores
  del negocio trabajarán en vistas propias con `rol_requerido`. Así ningún usuario con `is_staff`
  y permisos sueltos puede otorgarse privilegios.
- `base.html`: nombre del usuario, botón "Cerrar sesión" (POST) y enlace a Inicio en el menú.
- Base de datos:
  - Por acuerdo, `.env` usa `POSTGRES_PORT=5434`, porque el 5433 lo ocupa el PostgreSQL nativo del equipo.
  - `docker compose up -d` y primer `migrate` ejecutados.
  - `connect_timeout` de 10 s: si el servidor no responde, el error es claro y no hay espera indefinida.
- `POSTGRES_HOST` usa `127.0.0.1` por defecto, no `localhost`. En Windows, `localhost` prueba primero
  IPv6 (::1), donde Docker no publica el puerto, y cada conexión tardaba 10 s.
- `config/pruebas.py` es un ejecutor de pruebas con hash de contraseñas rápido y sin el ruido de axes.
  La suite pasó de 94 s a unos 5 s; producción no cambia.
- Pruebas:
  - Usuario y superusuario; correo duplicado con otras mayúsculas, rechazado en `create_user`, en el formulario y en la base.
  - Coordinador sin área y proveedor con área, rechazados.
  - Staff solo para roles admin; área protegida contra borrado.
  - Matriz de `rol_requerido` (4 vistas × 4 roles), 403 con la plantilla en español, sin sesión y usuario desactivado.
  - Login con mayúsculas, clave incorrecta, inactivo, `next` externo, bloqueo de axes y salir solo por POST.
  - Restricciones de la base probadas también con `.update()` y `bulk_create`.
  - Admin: solo entra un desarrollador superusuario activo. Se probaron el alta de coordinador con y sin área,
    la edición (normaliza el correo y desactiva), el rechazo de proveedor con área, el cambio de clave
    y el borrado bloqueado.
- Revisión adversarial con 3 revisores independientes. Se corrigieron:
  - posible escalada de privilegios desde el admin, ahora reservado a desarrolladores superusuarios;
  - correo con mayúsculas guardado por `.update()`, que dejaba al usuario sin poder ingresar;
  - código de área sin restricción en la base;
  - error de correo duplicado que salía dos veces en el formulario;
  - pruebas débiles o faltantes.
  Como no había commits ni datos, las migraciones `0001` se regeneraron.

### Verificado

- `python manage.py check`: sin errores.
- `python manage.py makemigrations --check`: sin cambios.
- `python manage.py test`: todas las pruebas OK.

## 2026-11-05 · Tarea 3: autenticación, seguridad de cuentas y bitácora

### Hecho

- **Rutas en la raíz:** `/ingresar/` (correo y clave), `/salir/` (solo POST; con GET responde 405 y no cierra
  la sesión) y `/cambiar-clave/`. Conservan los nombres `cuentas:ingresar`, `cuentas:salir` y
  `cuentas:cambiar_clave`.
- **Mensaje de error único:** el ingreso responde igual si la clave está errada, si el correo no existe o si
  la cuenta está inactiva, para no revelar si el correo está registrado.
- **Cambio de clave** (`cuentas/servicios.py: cambiar_clave`):
  - Vista de Django protegida con `rol_requerido`, abierta a todos los roles.
  - Formulario en español, que rechaza una clave nueva igual a la actual.
  - Al guardar se apaga `debe_cambiar_clave`, la sesión sigue abierta y el cambio queda en la bitácora.
- **`ObligarCambioClaveMiddleware`** (`cuentas/middleware.py`): con `debe_cambiar_clave=True`, toda URL
  redirige a `/cambiar-clave/`, incluidos POST y el admin técnico. Solo deja pasar `/cambiar-clave/`,
  `/salir/` y los estáticos, y el menú se oculta mientras tanto.
- **django-axes:**
  - 5 intentos fallidos bloquean **el correo** durante **15 minutos** (`AXES_LOCKOUT_PARAMETERS = ["username"]`).
  - El correo se normaliza, así que cambiar mayúsculas o IP no evita el bloqueo.
  - La página de bloqueo es genérica: también bloquea correos inexistentes, así que no revela cuáles existen.
  - El aviso `axes.W006` (no se bloquea por IP) se silencia de forma explícita en settings por ser la decisión acordada.
  - **Si el portal se publica en internet, se debe evaluar agregar también el bloqueo por IP** (por ejemplo
    `[["username"], ["ip_address"]]` con un límite más alto para la IP). Con bloqueo solo por correo, cualquiera
    puede bloquear la cuenta de otra persona durante 15 minutos con 5 intentos, y un atacante puede probar
    muchos correos distintos desde la misma IP sin ser frenado.
- **Sesión:**
  - `SESSION_COOKIE_AGE = 1800` y `SESSION_SAVE_EVERY_REQUEST = True`: se cierra tras 30 minutos sin actividad.
  - `SESSION_EXPIRE_AT_BROWSER_CLOSE = True`: también se cierra al cerrar el navegador.
- **Validadores de clave:** similitud con `correo` y `nombre`, longitud mínima 10, claves comunes y
  completamente numéricas. Los mensajes salen en español con la traducción de Django.
  - Se corrigió `UserAttributeSimilarityValidator`, que antes no comparaba con nada porque por defecto busca
    `username` y `email`, campos que este modelo no tiene.
- **Inicio por rol** (`cuentas/servicios.py: accesos_para`):
  - Coordinador: "Mi proyección".
  - Administrador y desarrollador: "Revisión", "Configuración" y "Proveedores".
  - Desarrollador superusuario: además, "Administración técnica".
  - Proveedor: redirige a `/portal/`.
  - Las pantallas que aún no existen aparecen como "Disponible próximamente" y se activan solas cuando se cree
    la URL con su nombre (`proyecciones:mi_proyeccion`, `proyecciones:revision`, `configuracion:inicio`,
    `proveedores:lista`).
  - El menú de `base.html` usa la misma lista (context processor `cuentas.contexto.accesos`) y el encabezado
    tiene enlaces a "Cambiar clave" y "Cerrar sesión".
- **App `portal`** (sin modelos): portada en `/portal/`, solo para el rol proveedor.
- **App `bitacora`** (solo inserción):
  - `RegistroBitacora` guarda fecha y hora, actor (y su correo como texto), acción, objeto, valor anterior,
    valor nuevo (JSON; Decimal como texto exacto), motivo e IP.
  - Nadie puede modificar ni borrar registros: lo impiden el modelo, el QuerySet y un **disparador de
    PostgreSQL** (migración `bitacora/0002`) que rechaza UPDATE y DELETE.
  - Servicios: `registrar`, `instantanea`, `diferencias` y `guardar_con_bitacora`.
  - En el admin técnico se consulta en solo lectura.
- **Admin técnico conectado a la bitácora:**
  - Alta y edición de usuarios (`cuentas.servicios.guardar_usuario`) y de áreas (`areas.servicios.guardar_area`):
    se registran solo los campos que cambiaron, con su valor anterior y nuevo.
  - Asignar una clave a otro usuario lo obliga a cambiarla en su próximo ingreso y queda en la bitácora.
  - En todos estos casos el **motivo es obligatorio**.
  - Los usuarios creados desde el admin quedan, por defecto, con cambio de clave obligatorio.
- Pruebas: ingreso correcto e incorrecto con el mismo mensaje en todos los casos, bloqueo al 5.º intento
  (los 4 anteriores responden 200), bloqueo por correo aunque cambien mayúsculas e IP, bloqueo de correo
  inexistente, desbloqueo a los 15 minutos, redirección obligatoria a cambiar clave (GET, POST, admin, rutas
  inexistentes) y paso libre a salir y estáticos, marca apagada tras el cambio, salir por GET no cierra
  la sesión y salir exige CSRF, sesión y cookie, validadores en español, inicio por cada rol, portal solo
  para proveedor, bitácora inmutable (modelo, QuerySet y SQL directo) y admin con motivo y bitácora.

- Revisión adversarial propia (seguridad, bitácora, pruebas y plantillas).
  - Se confirmó que no hay forma de saltarse el middleware (sin barra final, `/static/..`, HEAD y OPTIONS).
  - La sesión vence según lo pedido.
  - Cambiar la clave invalida las demás sesiones abiertas de ese usuario.
  - Se corrigieron dos defectos de la asignación de clave desde el admin:
    - ahora se guarda en la misma transacción que la bitácora (antes, si la bitácora fallaba, la clave
      cambiaba sin registro);
    - "Deshabilitar la autenticación basada en contraseña" se registra como `cuenta.clave_deshabilitada`
      y no marca cambio obligatorio.

### Verificado

- `python manage.py check`: sin errores (1 aviso silenciado a propósito: `axes.W006`).
- `python manage.py makemigrations --check`: sin cambios.
- `python manage.py test`: todas las pruebas OK.

## 2026-11-05 · Tarea 4: panel de configuración

### Hecho

- **App `proyecciones`**, por ahora solo con los catálogos:
  - `UnidadMedida`: nombre y abreviatura únicos sin distinguir mayúsculas, `activa`.
  - `ProductoSugerido`: nombre único, `unidad_por_defecto` (FK PROTECT) y `activo`.
  - Servicios en `proyecciones/servicios.py`, con bitácora. Un producto solo puede tomar una unidad activa,
    pero conserva la suya si esta se desactiva después.
  - En el admin técnico quedan en solo lectura.
- **App `configuracion`** (sin modelos): panel `/configuracion/`, protegido con
  `rol_requerido(administrador, desarrollador)` en cada vista. El acceso "Configuración" del inicio y del
  menú se activó solo.
  - **Áreas:**
    - Listado con búsqueda y filtro por estado, crear, editar, y activar o desactivar con confirmación.
    - **No se puede desactivar un área con coordinadores activos:** se pide reasignarlos o desactivarlos
      primero. La regla está en `areas/servicios.py` y la aplica también el admin técnico.
    - Asignar coordinadores: como cada coordinador tiene una sola área, asignarlo lo traslada desde la suya,
      y cada traslado queda en la bitácora del usuario.
    - Si no hay coordinadores disponibles, se muestra un aviso con enlace a "Crear usuario", con el rol y el
      área ya elegidos.
  - **Unidades de medida y productos sugeridos:** listado con búsqueda y filtro, crear, editar, y activar o
    desactivar.
  - **Usuarios:**
    - Listado con filtro por rol, área, estado y búsqueda, con paginación.
    - Crear: queda con `debe_cambiar_clave=True`. La clave temporal la **genera el sistema** (14 caracteres,
      sin caracteres que se confunden, cumple los validadores) y se muestra **una sola vez** en una página
      con `Cache-Control: no-store`; nunca va en la URL ni en la bitácora. También se puede **escribir a
      mano**, y se valida.
    - Editar datos, rol y área (sin tocar estado ni privilegios técnicos).
    - Activar o desactivar: el usuario desactivado pierde la sesión de inmediato.
    - Restablecer clave: genera o escribe una clave temporal, obliga a cambiarla y cierra las demás sesiones
      del usuario.
  - **Regla del desarrollador**, en el formulario y en el servicio (`cuentas/servicios.py: puede_gestionar`,
    `verificar_gestion`):
    - un administrador no ve la opción "desarrollador";
    - no puede crear ni editar desarrolladores, ni asignar ese rol;
    - no puede activarlos, desactivarlos ni restablecer su clave;
    - si fuerza la URL, recibe 403.
    - El panel nunca otorga `is_staff` ni `is_superuser`.
  - **Contra el autobloqueo:** nadie puede cambiar su propio rol, desactivarse ni restablecer su propia clave
    desde el panel.
  - **Nada se borra:** no hay vistas de borrado. Toda acción pide **motivo obligatorio** y queda en la
    bitácora con valor anterior y nuevo.
- **Mejoras transversales:**
  - `config/utilidades.py`: `normalizar_espacios` y `validar_unico_sin_mayusculas`. Con ellas, el error de
    nombre duplicado sale junto al campo, también en áreas.
  - `Usuario.clean` no permite asignar un área inactiva (sí conservar la que ya tenía).
  - `guardar_usuario` valida con `full_clean()`.
  - **Error 500 corregido.** Si se le quitaba el rol desarrollador a un superusuario desde un formulario sin el
    campo `is_staff`, Django fallaba con error 500. Ahora el error se muestra en el campo `rol`.
- Pruebas:
  - Matriz de las 20 URL del panel: 403 para coordinador y proveedor (GET y POST, sin cambios en los datos),
    login sin sesión y 200 para administrador y desarrollador.
  - CRUD de áreas, unidades, productos y usuarios.
  - Bloqueo al desactivar un área con coordinadores; desactivar un área no borra el área, sus usuarios ni su
    historial.
  - Traslado de coordinadores y aviso cuando no hay disponibles.
  - Regla del desarrollador en el formulario, en el servicio y por URL.
  - Clave temporal mostrada una sola vez, clave manual validada y usuario nuevo obligado a cambiarla al
    ingresar.
  - Restablecimiento que cierra las sesiones del usuario.
  - Protecciones contra el autobloqueo.
  - Bitácora con motivo en cada acción.

### Verificado

- `python manage.py check`: sin errores (1 aviso silenciado a propósito: `axes.W006`).
- `python manage.py makemigrations --check`: sin cambios.
- `python manage.py test`: todas las pruebas OK.

## 2026-11-05 · Tarea 5: modelos de la Fase 1 de proyecciones

### Hecho

- Se conservaron `UnidadMedida` y `ProductoSugerido` como catálogos existentes; no se duplicaron.
- Se agregaron los modelos `Periodo`, `ProyeccionArea`, `Linea` y `Ajuste` en la app `proyecciones`.
  - `Periodo` controla año único, fechas, estado abierto/cerrado y usuario creador.
  - `ProyeccionArea` relaciona un periodo con un área, con unicidad por ambos y trazabilidad de envío y aprobación.
  - `Linea` guarda producto o servicio, dependencia opcional, unidad, cantidades mensuales no negativas,
    precio estimado decimal y cantidad autorizada opcional.
  - `Linea.total_anual` y `Linea.costo_anual` calculan la suma anual y el costo usando `Decimal`, nunca `float`.
  - `Ajuste` exige justificación y solo admite líneas cuya proyección ya esté aprobada.
- Se reutilizó `bitacora.RegistroBitacora` como bitácora única: ya impide cambios y borrados en el modelo,
  el QuerySet y PostgreSQL. Los servicios nuevos registran actor, valores y motivo mediante el servicio común.
- Se agregaron servicios auditados para guardar periodos, proyecciones por área, líneas y ajustes.
- Se registraron los modelos nuevos en el administrador técnico en modo solo lectura.
- Se creó la migración `proyecciones/0002_linea_ajuste_periodo_proyeccionarea_linea_proyeccion_and_more.py`.
- Se agregaron pruebas para cantidades y precios negativos, unicidad periodo-área, cálculos con `Decimal`,
  ajustes justificados y registro de cambios. Las pruebas existentes de `bitacora` cubren su inmutabilidad.

### Verificado

- `python manage.py check`: sin errores (1 aviso silenciado a propósito: `axes.W006`).
- `python manage.py makemigrations --check`: sin cambios.
- `python manage.py test proyecciones`: 10 pruebas OK.
- `python manage.py test`: 206 pruebas OK.

## 2026-11-05 · Tarea 6: GDS-PRY-01 abrir y cerrar periodo

### Hecho

- Se agregó `/proyecciones/abrir-periodo/`, disponible únicamente para administradores y desarrolladores.
- La apertura se ejecuta en `proyecciones/servicios.py` dentro de una transacción: crea el periodo abierto
  y una `ProyeccionArea` en borrador por cada área activa; las áreas inactivas no reciben proyección.
- El año duplicado se rechaza con un mensaje en español y no deja registros parciales.
- La misma sección permite cerrar y reabrir periodos; ambas operaciones exigen motivo y quedan en la bitácora
  con la acción, el actor y los valores anterior y nuevo.
- Se agregó `Mi proyección` para coordinadores. Solo muestra las proyecciones de su área; un periodo abierto
  aparece como diligenciable y uno cerrado informa que la edición ordinaria está bloqueada.
- Los servicios de guardado de proyección y línea rechazan la edición de un coordinador sobre otra área o sobre
  un periodo cerrado.
- Al crear o reactivar un área con un periodo abierto sin proyección, configuración ofrece crearla desde la sección
  de periodos.
- Se agregaron formularios, URLs, plantillas, acceso de menú para administradores y pruebas de permisos y flujo.

### Verificado

- `python manage.py check`: sin errores (1 aviso silenciado a propósito: `axes.W006`).
- `python manage.py makemigrations --check`: sin cambios.
- `python manage.py test`: 218 pruebas OK.

## 2026-11-05 · Tareas 7: GDS-PRY-02 diligenciar líneas y GDS-PRY-03 guardar y enviar

### Hecho

- `Mi proyección` ahora muestra al coordinador únicamente la proyección de su área y permite trabajar el borrador
  mediante un `ModelFormSet` de Django.
- La tabla contiene producto o servicio, dependencia, unidad, los 12 meses, precio estimado, total anual y costo
  anual; las unidades deben estar activas y los meses son enteros no negativos.
- Se agregaron sugerencias de `ProductoSugerido`, filas adicionales y cálculos de total/costo en JavaScript para
  comodidad. Los valores oficiales siguen calculándose y validándose en el servidor con `Decimal`.
- Guardar borrador permite agregar, editar y quitar líneas. Cada creación, edición y eliminación queda en la
  bitácora con valores anterior/nuevo, actor, fecha y motivo.
- Enviar exige al menos una línea válida, registra fecha y usuario, cambia la proyección a `enviada` y la deja en
  solo lectura para el área. El periodo cerrado también bloquea cualquier edición ordinaria del coordinador.
- Las rutas con identificador filtran por el área del usuario; cambiar el ID no permite ver ni editar otra área.
- Se agregaron pruebas para formset, cantidades negativas/decimales, unidad, envío, solo lectura, eliminación,
  bloqueo por periodo cerrado y aislamiento por área.

### Verificado

- `python manage.py check`: sin errores (1 aviso silenciado a propósito: `axes.W006`).
- `python manage.py makemigrations --check`: sin cambios.
- `python manage.py test`: 226 pruebas OK.

## 2026-11-06 · Tarea 7 (cierre): revisión de GDS-PRY-02 y GDS-PRY-03

### Hecho

- **Formset protegido contra IDs ajenos** (`proyecciones/forms.py: BaseFormularioLineas`):
  - El campo oculto `id` de un formset de Django se valida contra todas las líneas de la base.
  - Antes, si alguien ponía el ID de una línea de otra área, el cambio se ignoraba en silencio.
  - Ahora se rechaza con el mensaje "Una de las líneas enviadas no pertenece a esta proyección", y no se guarda
    nada. Lo mismo pasa si una fila nueva trae el ID de una línea existente, lo que evita duplicarla.
- **Unidad activa validada en el servicio** (`guardar_linea`), no solo en el formulario:
  - Una línea nueva no puede usar una unidad inactiva, ni se puede cambiar a una.
  - Sí conserva la unidad que ya tenía aunque esta se desactive después.
  - La regla de productos sugeridos ahora usa el mismo helper (`_validar_unidad_activa`), sin duplicar lógica.
- **Accesibilidad:** cada casilla de la tabla tiene un `aria-label` con el campo y la fila, por ejemplo
  "Cantidad de enero, línea 2" o "Precio estimado, línea nueva".
- **Pruebas nuevas:**
  - Matriz de permisos para `mi_proyeccion` y `mi_proyeccion_detalle`: administrador, desarrollador y
    proveedor reciben 403 en GET y POST sin cambiar datos; sin sesión se redirige al ingreso; el coordinador
    del área accede.
  - Edición y eliminación de una línea ajena desde la URL propia, para guardar y para enviar.
  - ID repetido en una fila nueva.
  - Unidad inactiva en el servicio y conservación de una unidad desactivada después.
  - Etiquetas accesibles.
- Finales de línea normalizados a CRLF en `proyecciones/forms.py`, `urls.py`, `views.py`, las plantillas de
  `templates/proyecciones/` y `static/js/proyecciones.js`.

### Verificado

- `python manage.py check`: sin errores (1 aviso silenciado a propósito: `axes.W006`).
- `python manage.py makemigrations --check`: sin cambios.
- `python manage.py test`: 236 pruebas OK.

## 2026-11-06 · Tarea 8: GDS-PRY-04 revisión y corrección por administración

### Hecho

- **App `parametros`** (modelo de parámetros editables para las reglas "pendiente"):
  - Modelo `Parametro`: clave única, nombre, descripción, código de la decisión (p. ej. D-01), tipo (Sí/No, entero,
    decimal, texto), valor y valor por defecto. Los valores se guardan como texto y se convierten según el tipo.
  - `parametros/catalogo.py` documenta los parámetros conocidos y su valor por defecto.
  - `parametros.servicios.obtener(clave)`: si el registro no está en la base, usa el valor por defecto documentado.
  - `cambiar_valor`: solo administración, motivo obligatorio, rechaza valores inválidos o iguales al actual, y
    queda en la bitácora (`parametro.modificado`). No hay forma de borrar parámetros; en el admin técnico son de
    solo lectura.
  - La migración `parametros/0002` crea **D-01 `proyeccion.permitir_devolucion` = Sí** (valor por defecto).
  - Pantalla `/configuracion/parametros/` (listado y edición con motivo), en el submenú y el panel de configuración.
- **Revisión** (`/proyecciones/revision/`, solo administrador y desarrollador):
  - Listado de las proyecciones de todas las áreas con estado, fecha y usuario de envío, número de líneas y costo
    total, más el costo total del filtro. Los montos se calculan en PostgreSQL con `Decimal` (`resumen_revision`,
    `costo_total`); la suma de los meses usa `bigint` para no desbordar.
  - Filtros por periodo, área y estado. Sin filtros, muestra el periodo abierto más reciente (o el último si no hay
    abiertos); "Todos los periodos" muestra todo.
  - Detalle `/proyecciones/revision/<id>/`: líneas con total y costo, y el historial de la proyección y de sus
    líneas, incluidas las ya quitadas (`historial_proyeccion`).
- **Corrección de líneas** (`/proyecciones/revision/<id>/lineas/<id>/corregir/`, servicio `corregir_linea`):
  - Solo en proyecciones **enviadas**. Se puede cambiar cualquier campo que diligencia el área: producto,
    dependencia, unidad, los 12 meses y el precio.
  - La justificación (motivo) es obligatoria. La bitácora registra `linea.corregida` con el autor, solo los campos
    que cambiaron con su valor anterior y nuevo, y la justificación. Si no cambió nada, se rechaza.
  - Se aplican las mismas validaciones que para el área: cantidades enteras no negativas, precio con dos decimales
    y unidad activa (se conserva la que la línea ya tenía).
  - La línea se busca dentro de la proyección de la URL: otro ID da 404. El servicio exige además el rol de
    administración.
  - Se permite corregir aunque el periodo esté cerrado, porque la revisión puede hacerse después del cierre.
- **Devolución al área** (servicio `devolver_proyeccion`, decisión **D-01** por parámetro):
  - Pasa de enviada a borrador y limpia la fecha y el usuario de envío; sus valores anteriores quedan en la bitácora
    (`proyeccion_area.devuelta`) con el motivo.
  - Se bloquea si D-01 está en No, si la proyección no está enviada o si el periodo está cerrado (el área no podría
    corregir; se indica reabrirlo).
  - En "Mi proyección", el coordinador ve el aviso con la fecha, quién la devolvió y el motivo, y puede volver a
    editar y enviar.
- **Consulta de la bitácora** (`/proyecciones/bitacora/`, vista en la app `bitacora`, solo administración y solo GET):
  - Filtros por fechas (hora de Bogotá), actor, acción, tipo de objeto, ID del objeto y texto (objeto, actor o
    motivo). Paginación de 50.
  - Cada registro muestra los cambios campo por campo ("anterior → nuevo"), con los nombres de los campos en
    español, el motivo y la IP.
  - Acceso "Bitácora" en el inicio y el menú de administración; enlace desde la revisión y desde el detalle de cada
    proyección (filtrado por esa proyección).
- **Pruebas** (42 nuevas):
  - Coordinador y proveedor reciben 403 en GET y POST de todas las vistas nuevas, sin cambios en los datos; sin
    sesión, se redirige al ingreso.
  - Corrección sin motivo rechazada (vista y servicio).
  - La bitácora guarda autor, valor anterior, valor nuevo y justificación.
  - Corrección sin cambios, con cantidades o unidad inválidas, sobre proyecciones no enviadas y con una línea de
    otra proyección.
  - Devolver deja la proyección en borrador y el área ve el motivo; se bloquea sin motivo, con D-01 en No, con el
    periodo cerrado y para roles no administradores.
  - Costos con `Decimal`, filtros y periodo por defecto de la revisión.
  - Parámetros: conversión por tipo, valor por defecto, bitácora y permisos.
  - Filtros de la bitácora y rango de fechas inválido.

### Verificado

- `python manage.py check`: sin errores (1 aviso silenciado a propósito: `axes.W006`).
- `python manage.py makemigrations --check`: sin cambios.
- `python manage.py test`: 278 pruebas OK.
- `python manage.py migrate` se ejecutó en la tarea 9 (ver abajo).

## 2026-11-06 · Tarea 9: GDS-PRY-05 aprobación, cantidad autorizada y ajustes

### Hecho

- **Decisión D-01** (confirmado: cubre el flujo de aprobación completo). Tiene dos parámetros:
  - `proyeccion.permitir_devolucion` (Sí por defecto, de la tarea 8).
  - `proyeccion.aprobaciones_requeridas`, nuevo: entero, **1 por defecto** y mínimo 1. Se crea con la migración
    `parametros/0003`, y el mínimo se valida en el servicio y en el formulario de configuración.
- **Modelos** (migración `proyecciones/0004`):
  - `AprobacionProyeccion`: proyección, usuario, motivo, fecha y **fecha del envío aprobado**.
    - Un mismo usuario no puede aprobar dos veces el mismo envío (restricción única).
    - Una aprobación pertenece al envío que aprobó: si la proyección se devuelve y se vuelve a enviar, las
      aprobaciones anteriores dejan de contar, pero no se borran.
  - `Ajuste` ahora guarda también `valor_anterior` (el vigente antes del ajuste) y solo admite los campos
    ajustables.
  - Los dos modelos son de **solo inserción** (base `SoloInsercion`): ni el modelo ni el QuerySet permiten
    modificarlos ni borrarlos (`RegistroHistoricoError`).
  - En el admin técnico, `AprobacionProyeccion` es de solo lectura.
  - Se eliminó `guardar_ajuste`, que permitía modificar ajustes; lo reemplaza `registrar_ajuste`.
- **Servicios** (`proyecciones/servicios.py`):
  - `guardar_cantidades_autorizadas`: solo administración, con la proyección enviada y con motivo. Una casilla vacía
    toma el total anual. Cada cambio queda en la bitácora (`linea.cantidad_autorizada`).
  - `aprobar_proyeccion`: registra la aprobación (`proyeccion_area.aprobacion_registrada`). Cuando se alcanzan las
    aprobaciones requeridas:
    - pasa a `aprobada`, con `fecha_aprobacion` y `aprobado_por` (`proyeccion_area.aprobada`);
    - las líneas sin cantidad autorizada toman su total anual.
  - **Bloqueo** (`validar_no_aprobada`, que consulta el estado guardado en la base): `guardar_linea`,
    `eliminar_linea` y `guardar_proyeccion_area` rechazan cualquier cambio sobre una proyección aprobada, sea
    cual sea el rol. Corregir, devolver, autorizar y aprobar ya exigían que estuviera enviada.
  - `registrar_ajuste`:
    - solo administración, con la proyección aprobada y **justificación obligatoria**;
    - campos ajustables: cantidad autorizada, precio y los 12 meses;
    - el valor se valida con las reglas del campo (entero no negativo; precio con 2 decimales);
    - se rechaza un valor igual al vigente;
    - guarda el valor aprobado, el anterior y el nuevo, y registra `linea.ajustada` en la bitácora con la
      justificación como motivo;
    - **la línea no se modifica**: conserva el valor aprobado.
  - `valores_vigentes` y `anotar_vigentes`: el valor vigente es el aprobado o, si hay ajustes, el del último ajuste
    de cada campo. También calculan el total y el costo vigentes con `Decimal`.
- **Vistas y plantillas:**
  - Detalle de revisión, proyección **enviada**: tabla con la cantidad autorizada de cada línea (propone el total
    anual), motivo y botones "Guardar cantidades autorizadas" y "Aprobar proyección" (`/revision/<id>/aprobar/`,
    solo POST). Muestra las aprobaciones del envío actual y cuántas se requieren.
  - Detalle de revisión, proyección **aprobada**:
    - muestra los valores vigentes; las celdas ajustadas se resaltan con el valor aprobado como referencia;
    - muestra el costo aprobado y el vigente;
    - incluye la lista de ajustes y el enlace "Ajustar" en cada línea.
  - `/revision/<id>/lineas/<id>/ajustar/`: tabla de valores aprobados y vigentes, formulario del ajuste y ajustes
    anteriores de la línea.
  - "Mi proyección" (coordinador): cuando está aprobada, muestra la fecha y quién aprobó, los valores vigentes, la
    cantidad autorizada y la marca "Ajustada".
- **Pruebas** (26 nuevas):
  - Aprobación: guarda quién y cuándo, propone y aplica el total anual por defecto, admite cantidades distintas
    (con bitácora), guardar cantidades no aprueba, y se rechazan el motivo vacío, las cantidades negativas o
    decimales y una proyección que no está enviada.
  - Bloqueo tras aprobar:
    - el coordinador no puede editar;
    - administración no puede corregir, devolver ni volver a autorizar;
    - los 8 servicios ordinarios rechazan el cambio.
  - D-01: una aprobación por defecto; con 2, hacen falta dos administradores distintos; la devolución anula las
    aprobaciones parciales sin borrarlas; el parámetro no admite 0.
  - Ajustes:
    - sin justificación se rechaza (servicio y vista);
    - **el valor aprobado no cambia** y se muestra el vigente (incluso tras dos ajustes seguidos);
    - registra autor y bitácora, y el coordinador ve el valor vigente;
    - se rechazan valores inválidos, campos no ajustables y valores iguales al vigente;
    - solo se ajustan proyecciones aprobadas;
    - una línea de otra proyección da 404.
  - Aprobaciones y ajustes no se pueden modificar ni borrar.
  - Permisos: coordinador y proveedor reciben 403 (GET y POST), sin sesión se redirige al ingreso, y aprobar solo
    acepta POST.

### Verificado

- `python manage.py check`: sin errores (1 aviso silenciado a propósito: `axes.W006`).
- `python manage.py makemigrations --check`: sin cambios.
- `python manage.py test`: 304 pruebas OK.
- `python manage.py migrate` ejecutado en la base de desarrollo el 2026-11-06: se aplicaron `parametros/0001` a
  `0003` y `proyecciones/0002` a `0004`. Quedan creados los parámetros D-01 `proyeccion.permitir_devolucion = true`
  y `proyeccion.aprobaciones_requeridas = 1`.

## 2026-11-06 · Tarea 10: GDS-PRY-06 consolidado y exportación a Excel

### Hecho

- **`proyecciones/consolidado.py`**: todo se calcula con agregaciones de PostgreSQL y `Decimal`.
  - `lineas_con_vigentes(consulta)`: anota en cada línea los valores vigentes de los campos ajustables. Una
    subconsulta toma el último ajuste de cada campo y convierte su valor JSON con `#>> '{}'`; si no hay ajuste,
    queda el de la línea. También anota el total y el costo proyectados y ajustados (los meses se suman como
    `bigint`).
  - `filas_por_area(consulta)`: una fila por año y área del filtro, también las que no tienen líneas (en cero).
    Incluye número de líneas, los 12 meses, total anual, costo, cantidad autorizada, **cantidad ajustada**
    (autorizada vigente), total anual ajustado y **costo ajustado** (meses vigentes × precio vigente).
  - `totales(consulta)`: los mismos valores para todo el filtro. La cantidad autorizada y la ajustada quedan en
    `None` («—») si ninguna línea tiene valor.
  - `lineas_de(proyeccion)`: detalle de líneas para el Excel.
- **`/proyecciones/consolidado/`** (solo administrador y desarrollador, solo GET):
  - Usa los mismos filtros que la revisión (periodo, área y estado), con el periodo abierto más reciente por
    defecto. Ese filtro quedó en el helper `_filtrar_por_periodo_area_estado`, que comparten la revisión, el
    consolidado y la exportación.
  - Muestra una tabla por año y área con una fila de totales, el texto del filtro aplicado y un enlace al detalle
    de cada proyección.
  - Acceso "Consolidado" en el inicio y el menú de administración, y botón "Ver consolidado" en la revisión (lleva
    el mismo filtro).
- **`proyecciones/exportar.py`** y **`/proyecciones/consolidado/exportar/`** (mismos filtros):
  - Hoja "Resumen": título, filtro aplicado, una fila por año y área y una fila de totales.
  - Una hoja por proyección del filtro (por ejemplo "FAR 2031"), con sus líneas (valores proyectados, autorizada,
    ajustada, precio vigente y costo ajustado) y una fila de totales.
  - Encabezados con fondo azul #172554 y texto blanco en negrita, fila de encabezado fija, montos con formato
    `"$" #,##0.00`, enteros con separador de miles y anchos de columna.
  - Los totales se escriben como valores calculados en la base, no como fórmulas, para que coincidan exactamente
    con la pantalla.
  - `nombre_hoja`: nombres de hoja válidos para Excel (sin `\ / * ? : [ ]`, máximo 31 caracteres) y únicos.
  - La descarga lleva `Content-Disposition: attachment`, `Cache-Control: no-store` y `X-Content-Type-Options:
    nosniff`.
- **Pruebas** (13 nuevas):
  - Los totales y cada fila del consolidado coinciden con la suma de las líneas, calculada en Python, en 6 filtros:
    periodo actual, periodo anterior, un área en todos los periodos, aprobadas, borradores y todo. Los datos
    incluyen ajustes de cantidad autorizada, precio y meses.
  - Valores conocidos: costo 73,50, cantidad ajustada 13 y costo ajustado 102,00.
  - Una proyección sin líneas aparece en cero.
  - La vista respeta el filtro y el periodo por defecto.
  - El Excel, leído con openpyxl, tiene las mismas hojas, filas y totales que el consolidado, el detalle por área,
    el color de los encabezados, el formato de moneda, los filtros y el nombre del archivo.
  - Nombres de hoja.
  - Permisos: coordinador y proveedor reciben 403, sin sesión se redirige al ingreso, administración entra, POST da
    405 y el menú solo muestra el consolidado a administración.

### Verificado

- `python manage.py check`: sin errores (1 aviso silenciado a propósito: `axes.W006`).
- `python manage.py makemigrations --check`: sin cambios (esta tarea no tiene migraciones).
- `python manage.py test`: 317 pruebas OK.

## 2026-11-09 · Tarea 11: ficha de proveedor y documentos con vencimiento

### Hecho

- **App `proveedores`** (migraciones `0001` y `0002`):
  - `Proveedor`:
    - **NIT canónico y único:** se guarda solo con dígitos y sin ceros a la izquierda. Se aceptan puntos,
      espacios y guiones al escribirlo.
    - **Dígito de verificación aparte** (`digito_verificacion`), calculado con el algoritmo de la DIAN. Si se
      escribe (un guion seguido de un solo dígito al final, por ejemplo `900.123.456-8`), debe coincidir.
      `900-123-456` se lee como el NIT 900123456, no como un dígito de verificación.
    - Lógica en `proveedores/nit.py`. Restricciones en la base: NIT solo con dígitos, dígito entre 0 y 9, estado
      y tipo de persona válidos.
    - Razón social, tipo de persona (natural/jurídica), contacto (nombre, correo en minúsculas, teléfono),
      dirección, categoría (opcional), estado (registrado, en revisión, aprobado, inactivo) y fecha de registro.
  - `CategoriaProveedor` y `TipoDocumento` (`requiere_vencimiento`):
    - Son catálogos con nombre único sin distinguir mayúsculas. Se desactivan, no se borran.
    - Solo se puede elegir un registro activo; un objeto conserva el suyo aunque después se desactive.
    - La migración `0002` carga los valores iniciales: 8 tipos de documento (RUT, Cámara de Comercio,
      certificación bancaria, póliza, registro sanitario…) y 6 categorías.
  - `DocumentoProveedor`: proveedor, tipo, fecha de expedición, fecha de vencimiento, PDF **o** enlace (nunca
    ambos ni ninguno; lo exige una restricción en la base), nombre original del archivo, cargado por y fecha de
    carga.
    - La fecha de vencimiento es obligatoria si el tipo la requiere, y no puede ser anterior a la de expedición
      (también hay restricción en la base).
    - La fecha de expedición no puede ser futura.
    - El enlace solo admite http o https.
  - En el admin técnico, todo es de solo lectura y sin enlace al archivo.
- **`Usuario.proveedor`** (migración `cuentas/0002`):
  - FK opcional con `PROTECT`.
  - Regla en `clean()` y en un `CheckConstraint`: el rol proveedor exige ficha y los demás roles no pueden
    tenerla. No se puede asignar un proveedor inactivo, aunque el usuario conserva el que ya tenía.
  - La migración se detiene con instrucciones si ya hay usuarios con rol proveedor sin ficha, en vez de inventar
    fichas.
  - El campo se agregó al panel de usuarios y al admin técnico, y queda en la bitácora.
- **`proveedores/archivos.py`**, utilidad común de archivos privados (la usarán también las apps de compras):
  - `validar_pdf`: extensión `.pdf`, cabecera `%PDF-`, no vacío y máximo 10 MB.
  - `guardar_pdf`: guarda en `documentos/AAAA/MM/<uuid>.pdf` dentro de `MEDIA_ROOT`.
  - `borrar_al_confirmar`: borra el archivo con `transaction.on_commit`.
  - `borrar_ahora`: solo borra rutas con el formato exacto que crea el módulo (carpeta/AAAA/MM/uuid.pdf).
  - Señales (`proveedores/signals.py`): al borrar un documento, también con `QuerySet.delete()`, o al reemplazar
    su PDF o cambiarlo por un enlace, el archivo anterior se borra **solo si la transacción se confirma**. Si
    falla el guardado de un reemplazo, se borra el PDF nuevo y se conserva el anterior.
- **Servicios** (`proveedores/servicios.py`), todos con motivo obligatorio y bitácora, y solo para administración:
  - `guardar_proveedor` (`proveedor.creado` / `proveedor.modificado`): editar la ficha no cambia el estado.
  - `cambiar_estado` (`proveedor.estado_cambiado`): aprobar exige uno de los roles del parámetro D-03.
  - `guardar_documento` (`documento_proveedor.creado` / `.modificado`): registra solo los campos que cambiaron
    y rechaza guardar sin cambios. Un documento no se puede pasar a otro proveedor. Quien reemplaza el contenido
    queda como «cargado por».
  - `eliminar_documento` (`documento_proveedor.eliminado`): la bitácora conserva todos sus datos.
  - `buscar`: por razón social o por NIT escrito en cualquier formato.
  - Vencimientos (`vigencia`, `documentos_actuales`, `alertas_vencimiento`, `resumen_alertas`):
    - Un documento está **vencido** desde el día siguiente a su fecha de vencimiento, y **por vencer** si le
      quedan 30 días o menos.
    - Solo cuenta el documento más reciente de cada tipo por proveedor, así que renovar un documento apaga su
      alerta.
    - Los proveedores inactivos no generan alertas.
- **Parámetros nuevos** (`parametros/0004`, editables en `/configuracion/parametros/`):
  - **D-03 `proveedor.roles_aprobadores`** = `administrador,desarrollador`. Solo acepta roles de administración;
    se valida y normaliza con el nuevo `validador` de `DefinicionParametro`.
  - `proveedor.dias_alerta_vencimiento` = 30 (mínimo 1).
- **Vistas `/proveedores/`** (solo administrador y desarrollador, con `rol_requerido` en cada una):
  - lista con búsqueda por NIT o nombre, filtros por estado y categoría, y paginación;
  - ficha con datos, usuarios del portal asociados, enlace a su historial en la bitácora y documentos;
  - crear y editar la ficha, y cambiar su estado;
  - agregar, editar o reemplazar, y eliminar documentos (con confirmación y motivo);
  - descarga del PDF solo por `documento_descargar`, con `FileResponse` como adjunto,
    `X-Content-Type-Options: nosniff` y `Cache-Control: private, no-store`. El documento se busca dentro del
    proveedor de la URL, así que otro id da 404;
  - `/proveedores/vencimientos/`.

  El acceso «Proveedores» del inicio y del menú se activó solo.
- **Alertas:**
  - En la lista, la ficha y la página de vencimientos.
  - **Rojo solo para los vencidos** (`vigencia--vencido` y `mensaje--error`); los que están por vencer van en
    azul claro.
  - Estilos nuevos en `static/css/estilos.css`: `.vigencia--*`, `.ficha`, `.mensaje--info` y `.enlace-peligro`.
- `agregar_errores` se movió a `config/utilidades.py`; estaba duplicado en las vistas de `configuracion` y
  `proyecciones`.
- **Pruebas** (81 nuevas en `proveedores/tests/`, con `MEDIA_ROOT` temporal en cada prueba):
  - NIT en 8 formatos distintos: es el mismo NIT y no se duplica (modelo, servicio, formulario y base de datos).
    También se prueban el dígito de verificación errado, la búsqueda por NIT con formato y la edición con el NIT
    formateado.
  - PDF:
    - se rechazan un PDF falso (sin `%PDF-` o con la cabecera desplazada), uno de más de 10 MB, uno vacío y
      extensiones distintas;
    - se acepta uno de exactamente 10 MB;
    - nombre uuid dentro de `MEDIA_ROOT`;
    - `MEDIA_ROOT` no se publica por URL.
  - Borrado: borrar un documento borra su archivo (desde el servicio, la vista y `QuerySet.delete()`). Reemplazar
    el PDF o cambiarlo por un enlace borra el anterior. Si la transacción se revierte, el archivo se conserva. Si
    falla un reemplazo, no quedan PDF huérfanos.
  - Permisos:
    - las 10 URL usan `rol_requerido`;
    - coordinador y proveedor reciben 403 en GET y POST sin cambios en los datos;
    - **ni el usuario del propio proveedor descarga** desde la vista interna;
    - sin sesión se redirige al ingreso;
    - un documento de otro proveedor por URL da 404;
    - los servicios rechazan a quien no es de administración.
  - D-03 (por defecto y restringido a desarrollador), validación del parámetro, cambio de estado con motivo y
    bitácora, reglas de fechas, tipo y enlace del documento.
  - Vencimientos: clasificación en los bordes (hoy y hoy + 30), documento renovado, proveedor inactivo, días por
    parámetro y rojo solo para vencidos.
  - `Usuario.proveedor`: modelo, base de datos, proveedor inactivo, `PROTECT` y panel de usuarios con bitácora.
  - `crear_usuario` de las pruebas crea una ficha ficticia cuando el rol es proveedor.

### Verificado

- **Este equipo no pudo ejecutar las pruebas contra PostgreSQL.** El Control de aplicaciones de Windows bloquea
  `.venv\Scripts\python.exe` y la DLL de `psycopg[binary]` («Una directiva de Control de aplicaciones bloqueó
  este archivo»). Se verificó con el intérprete base de uv y una configuración temporal con SQLite que no está
  en el repositorio:
  - `check`: sin errores (1 aviso silenciado a propósito: `axes.W006`);
  - `makemigrations --check`: sin cambios;
  - `test`: 398 pruebas. Fallan solo las mismas 20 que ya fallaban en SQLite antes de esta tarea, porque son
    propias de PostgreSQL: el disparador de la bitácora y el operador JSON `#>>` del consolidado.
- **Pendiente de ejecutar en el equipo con PostgreSQL:** `python manage.py check`,
  `python manage.py makemigrations --check`, `python manage.py test` y luego `python manage.py migrate` (aplica
  `proveedores/0001-0002`, `cuentas/0002` y `parametros/0004`).

## Pendiente (vigente)

- **Evaluaciones FR-GDS-14:** versiones, respuestas/evidencias, cálculo/finalización,
  historial/anulación/copia y reglas documentales configurables ya implementados.
  Faltan la aprobación D-05 (exigencias oficiales) y D-06 (fórmula/umbrales) por negocio.
- **Proveedor inactivo y sus usuarios:** pasar un proveedor a «Inactivo» no desactiva a los usuarios de su
  portal. Decidir si debe hacerlo, como parámetro o como regla confirmada.
- **Transiciones de estado del proveedor:** hoy administración puede pasar de cualquier estado a cualquier otro.
  Solo «Aprobado» está restringido, por D-03. Si la clínica define un flujo (por ejemplo, exigir «En revisión»
  antes de aprobar, o documentos vigentes para aprobar), debe ir a parámetros.
- **Bloqueo por IP:** evaluarlo antes de publicar el portal en internet (ver Tarea 3).
- **Bitácora de gran volumen:** la consulta de `/proyecciones/bitacora/` arma las listas de actores, acciones y tipos
  a partir de los registros existentes. El FK de actor ya tiene índice; si crece mucho, revisar
  el tiempo de esas consultas y sus planes de ejecución.
- **Alcance de la bitácora:** registra lo que pasa por los servicios. Los cambios hechos directamente con el ORM
  o por shell no quedan registrados; toda pantalla nueva debe usar los servicios. `createsuperuser` tampoco se
  registra.
- **Clave temporal en la sesión:** queda guardada en la sesión del administrador solo hasta que se muestra. Si
  nunca abre la página, se borra cuando su sesión vence (30 minutos sin actividad) o al cerrarla.
- **Registro de ingresos y salidas:** los lleva django-axes (AccessLog y AccessFailureLog, visibles en el admin
  técnico); no se duplican en la bitácora.
- **`is_active` es una propiedad sobre `activo`**, así que no se puede filtrar en el ORM. Al crear la
  recuperación de clave, usar una subclase de `PasswordResetForm` cuyo `get_users` filtre por `activo=True`.
- **Recuperación de clave por correo:** no existe todavía. Por ahora el administrador restablece la clave desde
  `/configuracion/usuarios/`.
- **Proyección anual (FR-GDS-11):** el flujo completo ya existe: periodos, diligenciamiento y envío, revisión,
  corrección, devolución, aprobación, ajustes, consolidado, exportación e importación. El listado de revisión
  muestra ambos costos y los ajustes ya tienen índice. Si el volumen crece, medir las subconsultas del consolidado.
- **Cantidad autorizada mayor que el total anual:** hoy se permite. Si la clínica decide limitarla, debe ser un
  parámetro.
- **Decisión D-01 (flujo de aprobación):** dos parámetros editables en `/configuracion/parametros/`:
  - `proyeccion.permitir_devolucion` (Sí por defecto);
  - `proyeccion.aprobaciones_requeridas` (1 por defecto).

  Si se cambia el número de aprobaciones con envíos ya en curso, el nuevo valor se aplica en la siguiente
  aprobación; las proyecciones ya aprobadas no cambian.
- **Fecha límite de diligenciamiento:** hoy solo bloquea la edición el periodo cerrado; la fecha límite se muestra
  pero no bloquea. Si la clínica decide que la bloquee (o que permita un margen), la regla debe ir al modelo de
  parámetros editables, no fija en el código.
- **Cálculo en el navegador:** el costo que muestra el JavaScript es solo de comodidad (usa números de coma
  flotante); el valor oficial lo calcula el servidor con `Decimal`.
- Apps de compras (requisitos de selección, elegibles, cotización, orden y seguimiento). Para sus PDF deben
  reutilizar `proveedores/archivos.py`, con otra carpeta en `guardar_pdf(archivo, carpeta=...)`.
- Toda regla "pendiente" nueva debe agregarse a `parametros/catalogo.py` y crearse con una migración de datos, como
  D-01.
- Producción: `config/seguridad.py` toma la IP del cliente de la última entrada de
  X-Forwarded-For, lo que supone un solo proxy. Si hay varios proxies en cadena, hay que ajustarlo.
- `SESSION_SAVE_EVERY_REQUEST` escribe la sesión en la base de datos en cada petición. Es aceptable para el
  volumen previsto; si crece, evaluar sesiones en caché.
- En este equipo hay servicios PostgreSQL nativos en los puertos 5433 (versión 18) y 5432 (versión 14).
  Por eso Docker usa el 5434, definido en `.env`.
