# Bandeja de envíos · A15

Acceso: **Proveedores → Bandeja de envíos** (`/proveedores/bandeja/`).
Solo administradores y desarrolladores pueden consultar o revisar envíos.
Los proveedores conservan su acceso exclusivo por el portal.

## Consultar y revisar

La bandeja muestra pendientes por defecto. Puede combinar proveedor, búsqueda por
nombre o NIT con o sin formato, tipo de documento, estado y fechas de envío.
Seleccione «Todos los estados» para consultar el historial, y abra el detalle para
descargar el PDF y registrar una decisión con motivo obligatorio.

- **Aceptar documento:** crea un `DocumentoProveedor` con los datos del envío,
  reutilizando exactamente la misma ruta del PDF. No copia el archivo ni reemplaza
  documentos anteriores. Guarda el vínculo al documento, responsable, fecha y motivo.
- **Descartar envío:** conserva el registro histórico y el motivo. La conservación
  del PDF depende del parámetro descrito abajo.
- Un envío revisado no admite una segunda decisión. La revisión bloquea el registro
  dentro de una transacción: dos aceptaciones simultáneas no crean dos documentos.
- Aceptar o descartar solo admite POST con CSRF. El tipo y las fechas se vuelven a
  validar al aceptar; un archivo ausente o que ya no cumple las reglas de PDF impide
  la aceptación. Un tipo desactivado debe reactivarse antes de aceptar documentos nuevos.

## Envíos manuales

Seleccione «Registrar envío manual» para un PDF que llegó por correo u otro medio.
Elija un proveedor activo, tipo, fechas, archivo y motivo. El envío queda pendiente
y conserva al administrador como responsable de la carga. Sigue el mismo mecanismo
de revisión y archivos privados del portal, sin duplicar la lógica de carga.

## Retención y trazabilidad

`proveedor.conservar_pdf_descartado`, editable en Configuración → Parámetros:

- **Sí (predeterminado):** conserva el PDF descartado para consulta del historial.
- **No:** quita la referencia al archivo del envío y programa su borrado después
  de confirmar la transacción, únicamente si ningún otro registro lo referencia.
  Si la operación se revierte, el archivo se conserva.

El parámetro se aplica a descartes nuevos; cambiarlo no borra archivos de descartes
anteriores. El registro de envío, el nombre original y su bitácora siempre se conservan.
La clínica debe confirmar su política de retención antes de cambiar el valor.

Las cargas, aceptaciones y descartes guardan actor, fecha, motivo y valores anterior
y nuevo en bitácora. El documento de un envío aceptado no puede eliminarse rompiendo
esa relación; para renovarlo se incorpora otro documento y se mantiene el histórico.
Las descargas son adjuntos privados con `nosniff` y `no-store`; no hay rutas públicas
a los PDF.

## Próxima etapa

**A16:** versiones de la matriz FR-GDS-14 y creación de evaluaciones que conserven
la categoría y la versión utilizadas.
