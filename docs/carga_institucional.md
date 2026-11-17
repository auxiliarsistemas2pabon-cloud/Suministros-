# Información institucional en la plataforma principal

La sección **Información institucional** (`/suministros/`) reúne los seis formatos
originales, sus hojas/celdas, el histórico FR-GDS-27, los registros del FR-GDS-20 y
los cortes de numeración por área. Requiere una cuenta administrativa activa.
Las descargas conservan SHA-256 y no se sirven como archivos públicos.

La carga utiliza la base principal seleccionada en `.env`. No copia la base de
demostración, sus cuentas, proveedores, firmas, recepciones ni aprobaciones.
Tampoco convierte una fila histórica en una orden emitida nueva. Los textos y
valores combinados se conservan con su hoja y fila de origen.

## Carga repetible y trazable

Antes de cargar, respaldar la base con la utilidad del motor. El comando valida
las seis fuentes y cada celda del corte antes de realizar escrituras. La carga
de negocio es transaccional; repetir el mismo conjunto no duplica filas.

```powershell
python manage.py migrate
python manage.py cargar_institucionales entregables/gestion_suministros/Formatos_originales --corte entregables/gestion_suministros/Documentacion/Corte_de_numeracion.json --actor-id ID_EXISTENTE --motivo "Motivo autorizado de la carga" --verificar
python manage.py cargar_institucionales entregables/gestion_suministros/Formatos_originales --corte entregables/gestion_suministros/Documentacion/Corte_de_numeracion.json --actor-id ID_EXISTENTE --motivo "Motivo autorizado de la carga"
```

El actor debe ser un administrador o desarrollador activo existente. No se crean
credenciales ni se atribuyen firmas de aprobación durante una importación.
Los originales y el corte con datos institucionales permanecen fuera de Git.

## Numeración real por área

Las series se vinculan con el código de `Area`. Se conservan prefijos distintos,
incluidos GT/GTA y variantes históricas. Los nombres no documentados permanecen
identificados como pendientes, sin inventar una denominación de departamento.
Farmacia conserva números sin prefijo; «SIN PREFIJO» es una etiqueta de selección.

`numerar_al_emitir` usa la serie del área, su corte y el contador bloqueado en la
misma transacción de emisión. No reinicia anualmente las series importadas. El
mayor número registrado se conserva incluso si parece atípico. Los contadores
nunca retroceden; la anulación no libera un número. Una nueva área sin serie
configurada no puede emitir cuando ya existen series institucionales.

Los proyectos sin fuentes institucionales conservan el modo global/anual
anterior. Una orden existente conserva su número y sus reglas originales.

## Datos que requieren gestión humana

- El FR-GDS-11 recibido es una plantilla sin líneas diligenciadas: no genera
  proyecciones con cantidades inventadas.
- El FR-GDS-14 carga 26 requisitos y 286 pesos por 11 categorías en una matriz en
  borrador. Se debe confirmar la diferencia entre encabezado v04 y cambio v05
  antes de publicarla con vigencia institucional.
- El FR-GDS-20 carga los cuatro criterios y sus pesos 30/20/20/30 en borrador, y
  conserva aparte las calificaciones históricas del archivo.
- Las fórmulas identificables del Excel configuran umbrales 50/90 en FR-GDS-14 y
  método escalado a 100 en FR-GDS-20. Se conserva `pendiente=true` y no se
  sobrescriben parámetros que ya tengan una personalización distinta.
- Los nombres históricos sin NIT se consultan y permiten precargar el nombre en
  **Nuevo proveedor**. Una ficha operativa requiere la identificación real y la
  documentación aplicable.
- La razón social y NIT de la institución deben completarse en Parámetros para
  aprobar y emitir documentos reales. No se toman del ejemplo.
- Las pólizas del FR-GDS-28 se incorporan como opciones de catálogo; su sola carga
  no declara que sean obligatorias ni que un proveedor las haya presentado.

Las pruebas de importación, permisos, escapes HTML, rollback, idempotencia y
numeración se ejecutan con datos ficticios en la base aislada de pruebas.
