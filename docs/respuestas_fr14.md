# Respuestas y evidencias · A17

Desde una ficha de proveedor abra una evaluación FR-GDS-14. El detalle muestra
los requisitos de su versión y categoría, agrupados en Calidad, Ambiental y SG-SST,
con sus pesos y el contador de requisitos respondidos frente al total.

Seleccione **Responder** o **Corregir** en cada requisito. Elija Sí, No o No aplica,
escriba la observación y registre el motivo del guardado. **No aplica** requiere
marcar expresamente la confirmación y escribir una observación no vacía. No se
determina de forma fija su exclusión del máximo aplicable: se utiliza el parámetro
configurable de B1 (D-06), que por defecto excluye N/A.

## Evidencias

Puede seleccionar un documento de la ficha del mismo proveedor, adjuntar un PDF
propio o usar ambos. El servicio vuelve a comprobar que el requisito pertenece
a la versión y categoría de la evaluación y que el documento es de ese proveedor.

Los PDF propios se validan con las reglas comunes (extensión, cabecera `%PDF-`,
máximo 10 MB) y se guardan bajo `archivos_privados/evidencias/AAAA/MM/<uuid>.pdf`.
Los reemplazos y las desvinculaciones conservan el archivo anterior en el historial
de adjuntos de la evaluación. Las descargas están protegidas por rol y evaluación,
con adjunto, `nosniff` y `private, no-store`; no hay enlaces públicos al almacenamiento.

Al usar un documento de la ficha se guarda una foto de sus datos de respaldo:
tipo, archivo o enlace y fechas. Si se reemplaza su PDF, la evidencia original
se conserva y se descarga desde la respuesta. Los documentos vinculados no se
pueden eliminar rompiendo la referencia de la evaluación. Un enlace externo
puede cambiar fuera del sistema; cuando se necesite una copia conservada del
contenido debe adjuntarse el PDF.

## Trazabilidad y alcance

Una única respuesta por evaluación y requisito. Cada creación o corrección
registra responsable, fecha, motivo y valores anterior/nuevo en bitácora.
Las cargas fallidas revierten respuesta y adjunto y eliminan el PDF nuevo.
Las cargas de archivos no se ejecutan dentro de transacciones externas.

Solo administradores y desarrolladores acceden a respuestas y evidencias.
Coordinadores y usuarios proveedores reciben 403. Un adjunto consultado bajo
una evaluación distinta devuelve 404. El formulario usa POST con CSRF.

**B1 ya permite** calcular y finalizar conservando el resultado y las reglas D-06.
Las respuestas de una evaluación finalizada quedan en solo lectura. Consulte
[la guía de cálculo](calculo_fr14.md). Anulación, copia e identificación de la
evaluación vigente ya están disponibles en [B2](historial_evaluaciones.md).
