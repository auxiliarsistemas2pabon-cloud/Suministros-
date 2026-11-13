# Organización del frontend y el backend

La aplicación mantiene Django, plantillas del servidor, CSS propio y JavaScript
para las interacciones pequeñas. El trabajo local está en `C:\Suministros`;
esta reorganización no requiere publicar, hacer commits ni cambiar la base de datos.

## Backend

Cada aplicación representa una parte del proceso: `cuentas`, `proyecciones`,
`proveedores`, `portal`, `compras`, `seguimientos`, `configuracion`, `parametros`,
`areas` y `bitacora`. `config` contiene ajustes, rutas y utilidades comunes.

| Archivo o carpeta | Responsabilidad |
| --- | --- |
| `urls.py` | Rutas y nombres públicos de cada pantalla. |
| `views.py` y vistas por proceso | Métodos HTTP, permisos, formularios, respuestas y redirecciones. |
| `forms.py` y formularios por proceso | Entrada y validación del formulario. |
| `servicios.py` y servicios por proceso | Mutaciones, reglas de negocio, transacciones y auditoría. |
| `consultas.py`, donde existe | Lecturas y alcance de los datos que necesita la pantalla. |
| `models.py` y módulos de modelos | Estructura persistente, restricciones e invariantes. |
| `tests.py`, `tests/` y pruebas por proceso | Regresiones de permisos, reglas, integración y concurrencia. |

Las vistas siguen comprobando permisos en el servidor. Ocultar un enlace es una
decisión de presentación y no sustituye esa comprobación. Las mutaciones continúan
pasando por los servicios existentes para conservar transacciones y bitácora.

### Compras

`compras/models.py` es el punto de importación estable. Las definiciones antes
concentradas allí están agrupadas en `compras/modelos/`:

- `comunes.py`: protecciones compartidas del acceso ORM.
- `necesidades.py`: necesidad y procedencia.
- `elegibles.py`: participantes, criterios, calificaciones, decisión y cierre.
- `cotizaciones.py`: cabecera, numeración, líneas e invitados.
- `ofertas.py`: ofertas, impuestos, retenciones, PDF e historial.
- `verificaciones.py`: verificaciones de los oferentes y sus soportes.
- `proveedor_unico.py`: causales y evidencias del caso.
- `decisiones.py`: adjudicación y aprobación de cotizaciones.
- `contratos.py`: contratos, pólizas, soportes y revisiones.
- `ordenes.py`: orden de compra, líneas, revisiones y contador.

`compras/operacion_models.py` conserva las aprobaciones, evidencias de envío y
recepciones. Los servicios y migraciones existentes pueden seguir importando,
por ejemplo, `from compras.models import OrdenCompra`. No cambian los nombres
de modelos, las tablas ni el historial de migraciones. Las dependencias entre
los módulos de definiciones deben ser explícitas; evite importar la fachada
`compras.models` desde un archivo de `compras/modelos/`.

### Inicio y portal

- `cuentas/consultas.py` obtiene indicadores reales. Administración consulta
  pendientes operativos; coordinación recibe únicamente agregados de su área.
  El proveedor utiliza su portal y no recibe indicadores globales.
- `cuentas/navegacion.py` presenta los accesos definidos por rol en
  `cuentas/servicios.py`, los agrupa y determina la sección activa.
- `cuentas/contexto.py` entrega esa presentación a las plantillas, conservando
  el contexto de accesos anterior.
- `portal/consultas.py` limita las lecturas a la ficha de la persona autenticada.
- `config/descargas.py` entrega PDF con descarga privada, sin caché y con
  `nosniff`. La vista y la consulta deben autorizar primero el registro.

## Frontend

`templates/base.html` compone la estructura de las pantallas. Los fragmentos
compartidos viven en `templates/componentes/`: barra lateral, encabezado,
mensajes, pie, iconos SVG, indicadores y estado. Las pantallas de cada proceso
permanecen en su carpeta de plantillas.

La barra lateral distingue **Operación**, **Planeación** y **Administración**,
muestra la sección activa y se recoge con un botón en pantallas pequeñas.
Los catálogos de compras se agrupan en un desplegable nativo. El menú sigue
disponible si JavaScript no carga; el botón declara su estado con ARIA y permite
cerrar con Escape. La cuenta contiene el cambio de clave y la salida por POST.

`static/css/estilos.css` conserva las variables institucionales. `base.html`
enlaza directamente cada hoja; no depende de importaciones CSS anidadas. Después
de las variables, las hojas se cargan en este orden:

| Archivo | Contenido |
| --- | --- |
| `base.css` | Normalización, tipografía, enlaces y foco. |
| `componentes.css` | Botones, formularios, tablas, filtros, mensajes y utilidades. |
| `modulos.css` | Ajustes específicos de los procesos existentes. |
| `estructura.css` | Distribución general, barra lateral, encabezado y navegación móvil. |
| `panel.css` | Inicio, accesos e indicadores. |
| `ingreso.css` | Presentación exclusiva del inicio de sesión; se carga solo en esa pantalla. |

Cada archivo incluye las adaptaciones móviles de sus propios elementos.
Las URL usan una versión compartida (`version_interfaz` en `base.html`). Al
cambiar los recursos, incremente esa versión para evitar hojas anteriores en
la caché del navegador. Los SVG también declaran sus dimensiones y trazo en
el marcado para conservar su tamaño mientras cargan los estilos.
`static/js/interfaz.js` controla exclusivamente el menú adaptable; los scripts
existentes de cada proceso siguen utilizando el bloque `scripts` de la base.
`static/js/ingreso.js` permite mostrar u ocultar la clave mediante un botón
accesible. Sin JavaScript el campo continúa oculto y el formulario permite entrar.
No se incorporan dependencias de frontend ni recursos externos.

## Cómo continuar

1. Ubique el cambio en la aplicación responsable del proceso.
2. Reutilice los componentes de presentación y las variables de color.
3. Separe las lecturas complejas de las mutaciones y conserve el alcance por rol.
4. Use los servicios para guardar cambios con su motivo y auditoría.
5. Ejecute las pruebas afectadas y compruebe que un cambio de organización no
   genere migraciones inesperadas.

```powershell
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
.\.venv\Scripts\python.exe manage.py test --noinput
.\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8001 --noreload
```

Los datos reales, credenciales y PDF privados permanecen en sus ubicaciones
actuales. Los indicadores vacíos muestran cero; no se crean operaciones ficticias
en la base local para completar el panel. La razón social y el NIT de la clínica
se deben completar en Configuración → Parámetros antes de aprobar órdenes.
