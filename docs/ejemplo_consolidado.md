# Ejemplo desde el consolidado de compras de 2026

Abra **http://127.0.0.1:8002/ejemplo/**. La guía de esa pantalla enlaza cada
etapa y permite comparar los registros con su hoja y fila de Excel.

La demostración utiliza el consolidado proporcionado como origen de la
proyección. Los proveedores, documentos, ofertas, aprobaciones y movimientos
posteriores son ficticios. Los PDF de compra indican que no tienen validez
comercial. No se envían correos ni se realizan compras reales.

## Información cargada

Fuente: `FR-GDS-11 Proyeccion de compras (1) v3 (1).xlsx`, periodo **2026**.

| Área | Filas de origen | Cargadas | Valor de origen | Valor cargado |
| --- | ---: | ---: | ---: | ---: |
| Gestión Ambiental | 24 | 23 | 749.842.900,00 | 679.842.900,00 |
| Servicio Transfusional | 52 | 52 | 1.587.185.992,25 | 1.587.185.992,25 |
| Sistemas de Información | 53 | 53 | 1.017.129.333,33 | 1.017.129.333,33 |
| Total | 129 | 128 | 3.354.158.225,58 | 3.284.158.225,58 |

La diferencia de **70.000.000,00** corresponde a Sanisorb Active WEST, fila 26
de Gestión Ambiental. Junio (`I26`) y septiembre (`L26`) siguen pendientes por
confirmación del usuario. Se conservan como datos sin definir en la vista de
origen; esa fila no se cargó con cantidades cero.

Interpretaciones confirmadas por el usuario:

- La columna Q representa el **valor proyectado total** de la fila.
- Se utiliza «unidad» provisionalmente en todo el ejemplo.
- La «x» de noviembre en la fila 7 de Gestión Ambiental equivale a una unidad.
- Las cantidades vacías de Sanisorb todavía están pendientes.

Jornada reforestación conserva sus doce ceros explícitos y su presupuesto anual
de 6.000.000,00. No se inventa una cantidad ni un precio unitario: cuando el
modelo necesita una referencia técnica cero, las pantallas y exportaciones
indican que ese precio no fue informado.

Los totales almacenados al final de las hojas (`Q31`, `Q59`, `Q60`) difieren de
la suma de los importes de sus filas. La guía muestra esa diferencia, incluidos
los costos escritos como texto con símbolo monetario. Se conservó el archivo
original y una copia de origen con la misma huella SHA-256.

## Recorrido para explicar el proceso

1. **Proyección.** Consulte las tres áreas. Ambiental y Transfusional permanecen
   en borrador. Sistemas se envió y aprobó con actores ficticios para continuar
   el ejemplo. La columna P del Excel no se trató como una firma administrativa.
2. **Proveedores y evaluación.** Se crearon Tecnología Alfa DEMOSTRACIÓN y
   Tecnología Beta DEMOSTRACIÓN, con usuarios de portal, PDF de ejemplo,
   aceptación documental, evaluación FR-GDS-14 y otro envío pendiente de revisar.
3. **Necesidad y elegibles.** Una necesidad toma como origen la línea de equipos
   AIO, con autorización ficticia de cuatro unidades. La lista conserva criterios,
   calificaciones y su cierre.
4. **Cotización.** Dos proveedores presentan ofertas ficticias de 2.400.000 y
   2.500.000 por equipo, con impuesto del 0 % solo para este ejercicio.
5. **Decisión y contrato.** Se adjudica la oferta de menor valor y se conserva
   contrato, póliza y aprobación mediante los servicios del sistema.
6. **Orden.** `OC-2026-0001` compra cuatro equipos por **9.600.000,00**. Una persona
   administradora distinta del elaborador la aprueba. Consulte el PDF y la
   evidencia de envío registrada; no se mandó ninguna comunicación real.
7. **Recepción y seguimiento.** Se reciben dos equipos, se devuelve uno y luego
   se reciben tres. El resultado neto es cuatro recibidos, cero pendientes y el
   seguimiento cerrado. El historial permite consultar cada movimiento.

## Cuentas del ejemplo

| Correo | Función |
| --- | --- |
| `admin@demostracion.local` | Consulta general y elaboración |
| `aprobador@demostracion.local` | Otra persona administradora para las firmas |
| `soporte@demostracion.local` | Administración técnica del ejemplo |
| `area1@demostracion.local` | Coordinación de Gestión Ambiental |
| `area2@demostracion.local` | Coordinación de Servicio Transfusional |
| `area3@demostracion.local` | Coordinación de Sistemas de Información |
| `proveedor1@demostracion.local` | Portal del primer proveedor ficticio |
| `proveedor2@demostracion.local` | Portal del segundo proveedor ficticio |

La clave temporal compartida solo por estas cuentas de demostración se genera
al preparar el ejemplo y queda en `.demostracion/accesos.local.json`. Las cuentas
principales mantienen sus propias claves. La guía completa requiere administrador
o desarrollador; cada coordinador y proveedor conserva el alcance de su rol.

## Cómo volver a levantarlo

Si el ejemplo ya existe, basta ejecutar:

```powershell
.\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8002 --settings=config.settings_demo --noreload
```

Para preparar una demostración nueva en una base vacía, primero cree la carpeta,
aplique las migraciones del entorno demo y ejecute el comando:

```powershell
New-Item -ItemType Directory -Path .demostracion -Force
.\.venv\Scripts\python.exe manage.py migrate --settings=config.settings_demo --noinput
.\.venv\Scripts\python.exe manage.py preparar_ejemplo "C:\Users\USUARIO\Downloads\FR-GDS-11 Proyeccion de compras (1) v3 (1).xlsx" --settings=config.settings_demo --equis-como-unidad --unidad-provisional --recorrido
```

El comando rechaza la base principal y también rechaza una demostración que ya
contiene datos. No sobrescribe ni reinicia automáticamente el trabajo realizado.
Los datos, PDF y sesiones están separados bajo `.demostracion/`; esa carpeta está
excluida de Git. El servidor demo escucha únicamente en la dirección local.

## Pendiente de este consolidado

Definir junio y septiembre de Sanisorb antes de cargar esa línea. Para el uso
real también hay que sustituir las unidades provisionales y validar con la clínica
los totales de las hojas y las reglas de aprobación. Las firmas del ejemplo no
constituyen aprobación institucional del presupuesto proporcionado.
