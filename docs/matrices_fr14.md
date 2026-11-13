# Versiones de matriz y evaluaciones · A16

En **Proveedores → Matrices FR-GDS-14** puede consultar versiones, copiar una
matriz y publicar el borrador. Solo administradores y desarrolladores tienen acceso.

El catálogo existente se migra íntegramente a la versión 1 en borrador, conservando
los identificadores de requisitos y pesos. No se publica ni se certifica automáticamente
el contenido existente. Los textos oficiales siguen sujetos a aprobación de la clínica.

## Preparar y publicar

1. Complete requisitos y pesos en Configuración → Catálogos de proveedores,
   seleccionando la versión. Los pesos pertenecen a la versión de su requisito.
2. Para cambiar una matriz publicada, abra la versión y seleccione «Crear copia»
   con motivo. Se copian sus requisitos y pesos a un borrador con número nuevo.
3. Edite únicamente el borrador. Para cargar un CSV en una copia use:

   ```powershell
   .\.venv\Scripts\python.exe manage.py cargar_fr14 matriz.csv --matriz 2 --actor administrador@ejemplo.test --motivo "Actualización autorizada"
   ```

   Reemplace la ruta, número y correo por los correspondientes. Sin `--matriz`
   se utiliza la versión 1, que debe continuar en borrador para admitir cambios.
4. Publique indicando fecha inicial, final opcional y motivo. La publicación exige
   requisitos activos y pesos completos para las categorías incluidas.

Las vigencias incluyen ambas fechas. Una sucesora cierra la versión abierta
anterior el día previo y la marca retirada. Su contenido permanece congelado y
sigue siendo aplicable a fechas dentro de su intervalo, incluso si la sucesora
entra en vigencia en el futuro. Los intervalos publicados no pueden superponerse.
La publicación y la numeración se serializan con un bloqueo transaccional común.

Requisitos y pesos publicados o retirados no admiten cambios desde las pantallas,
los servicios, el guardado del modelo ni las actualizaciones/borrados de su queryset.
Las versiones y evaluaciones se conservan. Como en el resto del sistema, el acceso
directo por SQL corresponde al administrador técnico y no reemplaza los servicios auditados.

## Crear una evaluación

Desde la ficha del proveedor seleccione **Nueva evaluación FR-GDS-14**. Elija
categoría (se propone la de su ficha), fecha y motivo. Puede previsualizar la matriz
aplicable o crear directamente el borrador; si no hay versión aplicable o faltan
pesos para la categoría, no se guarda la evaluación.

La evaluación conserva proveedor, categoría, nombre de categoría, versión, fecha y
evaluador. Publicar otra versión no cambia sus requisitos ni pesos. El detalle es
consultable por administración y muestra el grupo y peso de cada requisito.

**A17 ya permite** guardar respuestas SI/NO/N/A y evidencias, con responsable,
fecha y motivo. Consulte [la guía de respuestas](respuestas_fr14.md). El cálculo
y la finalización están disponibles con [reglas D-06 provisionales](calculo_fr14.md).
