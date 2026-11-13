# Proveedor único en cotización · B12

Desde el detalle de una cotización abra **Proveedor único y justificación**.
Administración y Desarrolladores pueden consultar y modificar el caso mientras
la cotización esté en Borrador o En comparación. Decidida y Anulada permiten consulta.

## Confirmar el caso

La pantalla sugiere la selección inicial si hay exactamente una oferta registrada.
Los invitados sin oferta no se cuentan. Abrir la pantalla no marca el caso ni
genera historial; debe revisar y guardar con motivo.

1. Confirme el caso de proveedor único.
2. Seleccione una causal activa.
3. Escriba la especificación y justificación del caso, con el mínimo configurado.
4. Adjunte evidencia PDF si corresponde y guarde con motivo.

El caso conserva la identidad del proveedor y la revisión de la oferta al confirmar.
Una nueva oferta de otro proveedor exige revisar y desmarcar el caso antes de
decidir. Si sigue habiendo una sola oferta, desmarcar permite corregir el registro,
pero no permite decidir sin volver a confirmar y justificar el caso.

No se permite confirmar proveedor único sin ofertas o con varias ofertas. Esta
etapa prepara su validación; la comparación y decisión completas corresponden a B13.

## Causales y parámetros

En **Compras → Causales de proveedor único** puede crear, editar y desactivar
causales con nombre, descripción y orden. Se incluyen Exclusividad, Representación
de marca, Urgencia y Otra como valores editables. No representan una política
oficial de contratación. Los casos e historiales conservan el nombre confirmado
aunque después se renombre o desactive la causal.

Configure en **Configuración → Parámetros**:

| Parámetro | Inicial provisional | Efecto |
| --- | --- | --- |
| `cotizacion.proveedor_unico_min_caracteres` | 20 | Mínimo de caracteres de la justificación; admite enteros desde 1. |
| `cotizacion.proveedor_unico_evidencia_obligatoria` | No | Si se activa, el caso debe tener PDF al guardar y antes de decidir. |

Los valores iniciales requieren aprobación de la clínica. Se normalizan espacios
al validar la justificación: un texto vacío, solo espacios o espacios repetidos
no satisface el mínimo. Cambiar parámetros no reescribe lo guardado; antes de
decidir se deben cumplir las reglas vigentes.

## Evidencia e historial

Puede adjuntar un PDF de hasta 10 MB. Se valida extensión y cabecera y se guarda
con UUID en almacenamiento privado. Solo Administración y Desarrolladores pueden
descargarlo, dentro de la cotización correspondiente, con bitácora y sin caché.

Cada guardado conserva una revisión inmutable: selección, causal, justificación,
proveedor/oferta, reglas aplicadas, evidencia, usuario, fecha y motivo.
Reemplazar o retirar el PDF y desmarcar el caso conserva el historial y los archivos
anteriores. El número de revisión impide sobrescribir otro guardado sin recargar.

Una validación o auditoría fallida revierte el caso, revisión y adjunto, eliminando
solo el PDF nuevo sin confirmar. Las cargas rechazan transacciones externas para
evitar archivos huérfanos tras una reversión posterior.

## Validación para B13

`compras.proveedor_unico_servicios.validar_para_decidir(cotizacion, actor=...)`
lee el registro con bloqueo y devuelve una foto con las reglas vigentes. B13 debe
invocarlo dentro de su transacción de decisión y conservar esa foto con el resultado.
El validador no cambia el estado ni selecciona un proveedor. B13 ya lo integra en
la propuesta y antes de cada aprobación; consulte la [guía de decisión](decision_cotizacion.md).

Si hay una sola oferta, exige caso confirmado, causal, justificación y evidencia
según el parámetro actual. Si el caso está marcado, exige exactamente una oferta
y la identidad del proveedor confirmado. Sin ofertas no se permite decidir.

El guardado del modelo al pasar a Decidida ejecuta también esta validación B12;
las actualizaciones masivas de estado o campos del caso se bloquean. Este control
no sustituye las validaciones de comparación, verificaciones y selección de B13.

Veintidós pruebas en `compras/tests_proveedor_unico.py` cubren sugerencias sin
escrituras, causales, espacios y mínimo, evidencia configurable, validación de
decisión, revisión concurrente, historial, compensación de PDF, permisos y CSRF.
Las pruebas anteriores de solo lectura ahora preparan un caso válido antes de
poner una cotización de una oferta en Decidida.

B14 añade [contratos y pólizas](contratos_polizas.md), independientemente de si
la adjudicación se tramita como proveedor único.

B15 genera [órdenes desde la decisión aprobada](ordenes_compra.md), incluida la
adjudicación a un proveedor único, con una copia independiente de lo acordado.

Siguiente etapa: **B17, cálculo configurable de importes de la orden**.
