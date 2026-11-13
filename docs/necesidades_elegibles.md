# Necesidades y listas de elegibles · FR-GDS-20

La etapa B4 incorpora el origen de la compra y sus participantes en la app `compras`.
Esta app reunirá las siguientes etapas de elegibles, cotizaciones, órdenes y
seguimiento, reutilizando `proveedores` y `proyecciones`.

## Crear una necesidad

Ingrese con rol Administrador o Desarrollador y abra **Compras → Nueva necesidad**.
Registre objeto, área activa, fecha y motivo. El usuario que la crea queda como
responsable; la necesidad inicia abierta.

Para usar una proyección, consulte primero por área y, opcionalmente, periodo.
Solo se ofrecen líneas de proyecciones aprobadas del área. Agregue cada línea y
su cantidad tomada. Puede agrupar varias líneas en una necesidad o dividir una
línea entre varias necesidades. No repita la misma línea dentro de una necesidad.
Se admiten cantidades positivas con hasta tres decimales, almacenadas con Decimal.

Cada relación conserva la cantidad y una foto del producto, unidad, periodo y
cantidad autorizada vigente al crear la necesidad. Un ajuste posterior de la
proyección no modifica esos datos. Las cantidades de unidades diferentes se
presentan por separado y no se suman como si fueran equivalentes.

También puede registrar una necesidad sin proyección: deje las líneas vacías e
indique un tipo de origen o describa su origen en texto libre. Los tipos se
administran en **Compras → Tipos de origen** y desde Configuración. No se cargan
tipos oficiales inventados; se pueden crear, editar y desactivar con motivo.
Desactivar un tipo conserva las necesidades anteriores y evita nuevos usos.

La decisión D-09 sobre orígenes, agrupación y división sigue pendiente de aprobación
de la clínica. B4 proporciona las relaciones necesarias, sin inventar reservas,
consumos acumulados ni topes de cantidades entre necesidades. No representa una
autorización presupuestal ni control de existencias.

## Crear una lista y administrar participantes

Desde el detalle de una necesidad abierta, cree una lista indicando fecha y
motivo. La lista guarda su creador e inicia en borrador.

En la lista puede agregar proveedores activos de cualquier categoría. Cada
participante queda asociado a esa lista y necesidad, con el NIT canónico y razón
social que tenía al ingresar. Se impiden duplicados tanto por proveedor como por
NIT, con validación de servicio y restricciones de base de datos.

Retirar un participante exige motivo y lo deja inactivo; no borra el registro.
Volver a agregarlo reactiva la misma fila, conservando la identidad registrada.
La ficha actual del proveedor permanece disponible mediante un enlace y sus
cambios de nombre o NIT no reescriben la foto de la lista. El historial de retiros
y reactivaciones se consulta en la bitácora.

Solo se agregan o retiran participantes en borrador. Los servicios comprueban el
estado actual bloqueando la lista dentro de la transacción. La calificación se
incorporó en B5, la decisión en B6 y el cierre/reapertura/anulación en B8. Los estados
cerrada y anulada impiden modificaciones; cada cierre conserva su copia histórica.

## Permisos y trazabilidad

Todas las pantallas son internas para Administrador y Desarrollador. Coordinador
y Proveedor reciben 403, incluidos intentos POST directos. Los formularios usan
CSRF y las mutaciones exigen motivo también desde los servicios.

La creación de necesidades, relaciones de origen y listas, los cambios de tipos
y las altas, retiros y reactivaciones de participantes generan bitácora con actor,
fecha y valores. El cambio y su registro se guardan en la misma transacción; si
falla la auditoría, no se conserva una operación parcial. El administrador técnico
solo ofrece lectura para estos modelos.

Las pruebas de `compras/tests.py` cubren origen manual, agrupación/división,
cantidades inválidas, foto histórica, líneas no aprobadas o de otra área,
duplicidad de NIT, retiro/reactivación, estados, permisos, CSRF, filtros y el flujo
de formularios. Se ejecutan en SQLite y PostgreSQL.

La [guía de calificación](calificacion_elegibles.md) describe B5, criterios versionados,
escala, método de cálculo y la matriz de puntajes. La [guía de decisión](decision_elegibles.md)
describe B6: cantidades base, puestos y decisiones. La [guía del vínculo documental](vinculo_documental_elegibles.md)
describe B7: evaluación FR14, alertas y foto documental. La [guía de cierres](cierres_elegibles.md)
describe B8. Siguiente etapa: **B9, encabezado y líneas de cotización**.
