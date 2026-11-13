# Puestos y decisión de elegibles · FR-GDS-20

B6 agrega puestos, desempates justificados, cantidades autorizadas, observaciones
y exportación de la lista. Acceso: **Compras → Lista → Puestos y decisión**, con rol
Administrador o Desarrollador. D-08 sigue pendiente de aprobación de la clínica;
las reglas iniciales se identifican como provisionales en la pantalla y el Excel.

## Puestos y empates

El servidor ordena los totales Decimal de mayor a menor. De forma predeterminada,
los puntajes iguales comparten puesto con ranking denso: 5 / 5 / 3 da puestos
1 / 1 / 2. El empate por puntaje permanece visible. Un participante sin calificación
completa queda sin puesto; mientras exista alguno, los puestos son provisionales
y no se registra una decisión definitiva.

En cada grupo empatado puede ordenar manualmente a sus participantes mediante
selectores con nombre y NIT. Debe incluir a todos exactamente una vez e indicar
justificación y motivo. El desempate registra usuario y fecha, conserva el puesto
calculado por puntaje y muestra el puesto con el orden manual aplicado. Ejemplo:
el empate anterior puede convertirse en 1 / 2 / 3, sin cambiar los puntajes.

Puede restablecer el puesto compartido con motivo. Si cambian calificaciones o
participantes, los desempates activos se invalidan y deben revisarse; no vuelven
a aplicarse automáticamente aunque los puntajes regresen a valores anteriores.

## Cantidad base y unidad

Las necesidades admiten cantidad base explícita y unidad, desde su creación o
desde **Definir o revisar cantidad base y unidad**. Deben indicarse juntas; la
cantidad es positiva, con hasta tres decimales.

Si no hay base explícita y todas las líneas de origen tienen la misma unidad,
se suman las cantidades tomadas con Decimal y se conserva la unidad del origen.
Si no hay proyección o se mezclan unidades, debe definir una base expresamente,
por ejemplo una unidad de contratación. El sistema no convierte ni suma cajas,
frascos u otras unidades incompatibles como si fueran equivalentes.

Cambiar la base exige motivo e invalida las decisiones de todas sus listas en
borrador. Si alguna lista está cerrada o anulada, la base se conserva. La política
D-09 sobre reservas y consumo entre necesidades sigue pendiente: el tope de B6 se
aplica a los participantes activos de una misma lista, sin descontar otras listas
ni reservar cantidades de proyecciones.

## Registrar la decisión

Complete primero la calificación de todos los participantes activos. Por cada uno
indique cantidad autorizada, observación libre y justificación de elección cuando
corresponda. Las cantidades admiten cero y hasta tres decimales; una cantidad
positiva indica elección y debe existir al menos una.

- La suma autorizada no supera la cantidad base, salvo excepción con justificación.
- Elegir con cantidad positiva a un participante fuera del primer puesto exige
  justificación particular. El puesto considera el desempate manual aplicado.
- Si solo hay un participante activo, se exige justificación de proveedor único.
- Los empatados sin desempate manual conservan el mismo puesto; elegir a cualquiera
  de los que comparten el primer puesto no simula haber resuelto ese empate.

Guardar registra las cantidades y justificaciones, quién decidió y cuándo, así
como el contexto de puntajes, puestos, versión, reglas y cantidad base. Todos los
cambios se guardan con su bitácora en la misma transacción. Un error de validación
o auditoría revierte también las asignaciones parciales.

Si después cambia una calificación, se agrega, retira o reactiva un participante,
se cambia la cantidad base o se aplica/restablece un desempate, la decisión queda
pendiente de revisión. Las cantidades anteriores permanecen visibles para revisión;
no se presentan como una decisión vigente. Un guardado de calificaciones sin cambios
no invalida nada. El formulario detecta cambios desde que se abrió y exige recargar.

Solo el borrador admite decisiones, desempates y cambios de cantidades. La función
`validar_para_cierre` comprueba que haya decisión vigente, calificaciones completas,
cantidad base, elección y justificaciones exigidas. B8 la reutiliza al cerrar la
lista, junto con el control documental. No crea cotizaciones u órdenes.

## Exportar

**Exportar lista a Excel** descarga un libro con:

- Elegibles: identidad registrada, puntaje, máximo, puesto calculado, puesto con
  desempate, bandera de empate, cantidad, unidad, observación y justificación.
- Calificaciones: cumplimiento, peso, subtotal y observación por criterio.
- Decisión y reglas: escala, fórmula, redondeo, aprobaciones pendientes,
  justificaciones generales y desempates con sus responsables y fechas.

Los encabezados reutilizan el azul del consolidado de proyecciones, con paneles
inmovilizados y formatos numéricos. Los valores se calculan en servidor y se
escriben sin fórmulas. NIT y textos del usuario se guardan como texto, incluso si
comienzan por `=`; se eliminan caracteres que Excel no admite. Una decisión no
vigente se identifica expresamente como pendiente en el libro. La descarga exige
permisos y queda en bitácora.

Las pruebas en `compras/tests_decision.py` verifican empates, desempate y
restablecimiento, proveedor único, excepciones, suma Decimal, unidades mixtas,
invalidación, atomicidad, exportación, formularios, CSRF y permisos.

El [vínculo documental de B7](vinculo_documental_elegibles.md) muestra la evaluación
FR14 y sus alertas. La [guía de cierres](cierres_elegibles.md) describe B8.
Siguiente etapa: **B9, encabezado y líneas de cotización**.
