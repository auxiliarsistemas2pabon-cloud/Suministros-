# Estado de los prompts · 12 de noviembre de 2026

Comparación del código y sus pruebas con `Prompts_desde_cero_Gestion_de_suministros.md`.
El documento se usa como hoja de ruta; sus solicitudes de confirmaciones y commits no
se ejecutan automáticamente. Los estados indican implementación técnica, no aprobación
de las reglas pendientes por parte de la clínica.

| Prompts | Estado | Evidencia o pendiente |
| --- | --- | --- |
| A1 | Implementado con diferencias de entorno | Proyecto, configuración, Docker, documentación y estilos. SQLite local y PostgreSQL seleccionable; falta establecer el primer commit. |
| A2–A3 | Implementados | Usuario propio, roles, alcance, ingreso, bloqueo y cambio obligatorio de clave; pruebas en `cuentas/tests/`. |
| A4 | Implementado | Panel de áreas, usuarios, unidades, productos y parámetros; pruebas en `configuracion/tests/`. |
| A5–A7 | Implementados | Modelos, periodos, borradores, envío y validación por área en `proyecciones/`. |
| A8–A9 | Implementados | Revisión, corrección, devolución configurable, aprobaciones y ajustes históricos. |
| A10 | Implementado | Consolidado y exportación con filtros, valores originales y vigentes. |
| A11 | Implementado y revisado | Plantilla, lectura acotada de Excel, vista previa en servidor y confirmación transaccional. Se verifican también las dimensiones reales de la hoja. |
| A12 | Implementado | Categorías con descripción, tipos y alertas particulares, Requisito y Peso, pantallas de configuración, carga CSV auditada e idempotente y ejemplo ficticio de 26 requisitos. |
| A13 | Implementado | Ficha, NIT, documentos privados, vencimientos, relación Usuario.proveedor y pruebas en `proveedores/tests/`. |
| A14 | Implementado | Registro público con activación configurable, protección básica por IP y campo trampa, ficha propia, envíos PDF privados e historial y descargas limitados al proveedor. |
| A15 | Implementado | Bandeja con filtros, PDF protegidos, aceptación atómica reutilizando el archivo, descarte con retención configurable, cargas manuales y bitácora. |
| A16 | Implementado | Catálogo migrado a versión 1 en borrador, copias, publicación con vigencias sin solapamientos y evaluaciones con categoría y versión fijas. |
| A17 | Implementado | Respuesta única por requisito, SI/NO/N/A con confirmación explícita, documentos propios y PDF privados, agrupación por grupo, avance y cambios auditados. |
| B1 | Implementado técnicamente | Cálculo Decimal, reglas D-06 editables, desglose y finalización con foto inmutable. Fórmula, umbrales y hoja oficial siguen pendientes de aprobación de la clínica. |
| B2 | Implementado | Historial, evaluación vigente reutilizable, anulación con motivo y copia independiente de respuestas/evidencias sin duplicar PDF. |
| B3 | Implementado técnicamente | Exigencias configurables por categoría/requisito, cuatro estados documentales, evidencia a fecha de evaluación, advertencia/bloqueo D-05 y filtros de vencimientos. La lista oficial está pendiente de aprobación de la clínica. |
| B4 | Implementado técnicamente | App compras, necesidades con origen manual configurable o líneas aprobadas y cantidades Decimal, listas en borrador y participantes únicos por proveedor/NIT, retiros y reactivaciones auditados. La política de reserva y topes D-09 sigue pendiente. |
| B5 | Implementado técnicamente | Criterios versionados con pesos de suma 100 %, vigencias sin solapamiento y publicaciones conservadas; matriz con cumplimiento/observación y cálculo Decimal directo o escalado. Escala y método fijos por lista. D-07 y el ejemplo funcional requieren aprobación de la clínica. |
| B6 | Implementado técnicamente | Puestos densos, empates y desempates justificados, cantidad base con unidad, asignaciones Decimal, proveedor único y excepciones auditadas, invalidación de decisiones y Excel. D-08 sigue pendiente; validador de decisión preparado para el cierre B8. |
| B7 | Implementado técnicamente | Evaluación FR14 vigente, antigüedad en meses calendario, tablero documental y alertas por participante. Modos advertir/bloquear y justificación de elegidos; servicio de foto y referencia fija preparado para el cierre B8. Valores iniciales y D-05 pendientes de aprobación. |
| B8 | Implementado técnicamente | Cierre transaccional B5/B6/B7 con actor/fecha y foto completa; archivo inmutable por ciclo, reapertura/anulación auditadas y estados en necesidades. Precarga sin escrituras; integración real con cotización completada en B9. |
| B9 | Implementado técnicamente | Cotización con necesidad, lista/cierre opcionales, fecha, área, responsable, tipo y consecutivo; líneas con cantidad/unidad/especificación y origen. Invitaciones desde elegidos, creación explícita, límites 3/10 configurables con 0 sin límite de negocio, navegación y bitácora. D-10 pendiente de aprobación. |
| B10 | Implementado técnicamente | Oferta única por proveedor/cotización con revisiones y PDF privados conservados; precios por especificación, tarifas configurables y totales Decimal en servidor. Redondeo inicial a pesos ROUND_HALF_UP editable; solo tarifa 0 % precargada. D-11 pendiente de aprobación. |
| B11 | Implementado técnicamente | Tipos y estados configurables; matriz por oferente con alertas, usuario/fecha, revisiones y PDF privados. Propuesta documental B3 a fecha con confirmación explícita y foto conservada; revisión requerida al cambiar la oferta. Obligatoriedad oficial pendiente de la clínica. |
| B12 | Implementado técnicamente | Caso de proveedor único sugerido por una oferta, confirmado con causal, justificación mínima configurable y PDF según parámetro. Revisiones/evidencias privadas, bitácora y validador para decisión B13, con protección de transición a Decidida. Valores provisionales pendientes de la clínica. |
| B13 | Implementado técnicamente | Comparativo por línea/oferente con costos e impuestos guardados, menores en azul, B11 y puntaje del cierre de elegibles. Adjudicación completa o por línea, justificaciones, N aprobaciones distintas configurables, decisión inmutable/anulación con motivo y Excel histórico. Modalidad inicial completa elegida por el usuario; aprobación y control provisionales pendientes de la clínica. |
| B14 | Implementado técnicamente | Requiere contrato por cotización y contrato uno a uno con decisión, supervisor usuario/texto, fechas, pago, valor y PDF. Pólizas con tipos editables, vigencias y alertas B3. Obligatoriedad por campo y exigencia de póliza configurables; validación antes de firmar, foto por aprobación, bloqueo tras la primera firma e historial privado. Valores provisionales pendientes de la clínica. |
| B15 | Implementado técnicamente | Orden en borrador por proveedor desde foto/revisión aprobadas, copia independiente de líneas, impuestos y pago contractual, creación idempotente/transaccional, cambios con original/actual y revisiones, anulación coordinada de borradores y trazabilidad hasta FR14/proyección. Numeración B16 e importes B17 completados; aprobación/emisión por interfaz pendiente en B18. |
| B16 | Implementado técnicamente | Motor de numeración al emitir, formato prefijo/año/longitud y reinicio anual configurables, contador bloqueado y restricciones únicas, reglas/actor/fecha conservados y anulación sin reutilización. Fecha opcional con etiqueta D-13. La interfaz y autorización de emisión se integrarán en B18; D-12/D-13 requieren aprobación de la clínica. |
| B17 | Implementado técnicamente | Motor Decimal puro, descuentos antes/después del impuesto, redondeo por línea/total con distribución, tarifas y retenciones configurables con mínimo opcional, receta guardada y adopción explícita. Foto y validación al emitir, desglose e historial; casos ficticios pendientes de validar con financiera (D-11). |
| B18 | Implementado técnicamente | Reglas por total/categoría, firmas por ciclo de personas distintas, rechazo a borrador y emisión atómica con consecutivo. PDF FR-GDS-21 directo elegido por el usuario, clínica configurable y foto conservada, evidencias privadas de envío. Otra persona administradora distinta del elaborador elegida por el usuario. |
| B19 | Implementado técnicamente | Libro inmutable de recepciones y ajustes, aceptado/rechazado/pendiente, estado derivado, excesos con habilitación y autorización expresa, PDF privados. Usuario eligió solo administradores y desarrolladores; coordinador por área preparado y deshabilitado. |
| B20 | Implementado técnicamente | Seguimiento desde orden emitida o contrato aprobado, copia del origen, corrección auditada, creación automática configurable e idempotencia por orden. |
| B21 | Implementado técnicamente | Catálogo de eventos, fecha del evento/registro y autor separados, correcciones enlazadas sin edición/borrado, soportes privados y línea de tiempo. |
| B22 | Implementado técnicamente | Reutiliza recepciones; devoluciones y ajustes con signo, tabla de pendientes, cierre/reapertura de líneas con motivo y eventos automáticos sin duplicar PDF. |
| B23 | Implementado técnicamente | Derivación pura de estados con fecha inyectada, plantillas de hitos sin SLA reales, versiones conservadas, entrega esperada, próximos vencimientos y comando de atrasos. Prioridades y plazos D-15 pendientes de validación clínica. |
| B24 | Implementado técnicamente | Cierre con resultado/fecha/observación/autor, bloqueo o advertencia de saldos, conservación del historial y cierre de orden compatible. Reapertura administrativa con motivo, inicialmente deshabilitada. |
| B25 | Implementado técnicamente | Reportes con filtros combinables, paginación, agregados de valor y cantidades por unidad en base de datos, Excel con mismo alcance y consulta futura por área preparada. |
| B26 | Revisado técnicamente | Suites conservan protección de desarrolladores, descargas propias y limpieza transaccional de PDF. Las referencias nuevas de envío/recepción/evento protegen archivos compartidos. Seguridad configurable y finales CRLF revisados; scripts Linux usan LF explícito. |
| B27 | Implementado técnicamente | Componente y servicio compartidos con alcance antes de filtros, listados por módulo y Excel equivalente, búsqueda superior por NIT normalizado/consecutivo. Panel de seguimientos combina estado derivado y demás filtros. |
| B28 | Preparado; validación de VM pendiente | Guía Ubuntu 24.04/Python 3.13/PostgreSQL 18, plantillas Gunicorn/nginx y entorno sin secretos. Respaldo con pg_dump, privados, SHA-256 y rotación 7/4, restauración probada en bases aisladas. check --deploy ejecutado con entorno temporal. Falta instalar la VM y verificar allí systemd/nginx/HTTPS. |

## Trabajo restante de aceptación y operación

1. A14–A17 y B1–B27 cuentan con implementación técnica; B28 entrega la preparación de despliegue.
2. Validar con la clínica las decisiones D-01 a D-17, tasas, casos financieros, matriz de aprobaciones, documentos, SLA y recepción.
3. Configurar razón social/NIT de la clínica y ejecutar el recorrido funcional con datos de prueba acordados.
4. Instalar la VM Ubuntu, completar entorno/certificados y probar systemd, nginx, HTTPS y recuperación operacional según `despliegue.md`.
5. Las preferencias confirmadas del usuario se conservan: otra persona aprueba, PDF directo y recepción administrativa.

## Límites de la verificación

- La entrega anterior se comprobó con Python 3.12 y SQLite. En esta revisión se
  preparó `.venv` con Python 3.13.15 y Django 5.2.19; la verificación final de
  SQLite y PostgreSQL 18 se registra en `avances.md`.
- Los cálculos y parámetros de negocio provisionales siguen necesitando validación de la clínica.
- No se han creado commits ni hecho push. El repositorio ya estaba sin archivos rastreados;
  esta entrega conserva ese estado.
