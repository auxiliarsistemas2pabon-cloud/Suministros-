# Carga del catálogo FR-GDS-14

El archivo `fr14_ejemplo.csv` contiene **26 requisitos y 52 pesos ficticios**,
repartidos en Calidad, Ambiental y SG-SST y dos categorías de demostración.
No representa la matriz oficial de la clínica. No se carga automáticamente al migrar.

## Formato

CSV UTF-8, con o sin BOM, separado por comas y con estos encabezados en este orden:

```csv
grupo,numero,texto,categoria,peso
calidad,1,Texto ficticio para demostración,Categoría ficticia de insumos,2
calidad,1,Texto ficticio para demostración,Categoría ficticia de servicios,1
```

- `grupo`: `calidad`, `ambiental` o `sgsst`.
- `numero`: entero positivo, único para cada requisito. El mismo requisito puede
  aparecer en varias categorías, conservando exactamente el grupo y el texto.
- `texto`: no vacío. Las comas y saltos de línea deben ir dentro de comillas CSV.
- `categoria`: nombre no vacío de hasta 120 caracteres.
- `peso`: exclusivamente `1` o `2`.
- No se repite una pareja requisito/categoría dentro de un mismo archivo.
- Límites técnicos: 2 MB y 5000 filas.

## Ejecutar

Use el correo de un administrador o desarrollador **activo que ya exista**:

```powershell
.\.venv\Scripts\python.exe manage.py cargar_fr14 docs/ejemplos/fr14_ejemplo.csv --actor administrador@ejemplo.test --motivo "Carga de demostración autorizada"
```

Cambie el correo del ejemplo por el actor real. Para los datos oficiales sustituya
la ruta por el CSV aprobado por la clínica.

El comando valida el archivo completo antes de guardar. Una falla revierte toda la
carga. Repetir el mismo CSV no duplica requisitos, categorías, pesos ni registros de
bitácora. Si cambia un texto, grupo o peso existente, conserva su valor anterior,
nuevo, autor, fecha y motivo. No reactiva catálogos desactivados ni borra datos
ausentes del archivo. Un peso nuevo exige requisito y categoría activos.

## Configuración web

Con A16, cada requisito pertenece a una versión. El comando admite `--matriz N`
para elegir una copia en borrador. Una matriz publicada o retirada no acepta cargas;
consulte [la guía de versiones](../matrices_fr14.md) para crear y publicar una sucesora.

Entre en **Configuración → Catálogos de proveedores**. Desde allí puede crear y
editar categorías, tipos de documento, requisitos y pesos; las categorías, tipos
y requisitos se desactivan o reactivan con motivo. El peso se modifica sobre la
misma pareja requisito/categoría para conservar su identidad.

Los tipos de documento usan por defecto el plazo general de alerta. Para un plazo
particular, desmarque «usar los días de alerta generales» e indique un número de
días mayor que cero. Cambiar el plazo no modifica las fechas de los documentos.
