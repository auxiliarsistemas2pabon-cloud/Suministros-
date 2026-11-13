# Sistema de Gestión de Suministros

Aplicación web en Django para gestionar el ciclo de suministros de una clínica:

FR-GDS-11 Proyección anual → FR-GDS-14 Requisitos de selección de proveedores →
FR-GDS-20 Lista de elegibles → FR-GDS-28 Cotización → FR-GDS-21 Orden de compra →
FR-GDS-27 Seguimiento.

## Tecnologías

La [guía de arquitectura](docs/arquitectura.md) describe dónde modificar el
backend, los componentes de plantillas, los estilos y la navegación por rol.

- Python 3.13
- Django 5.2
- SQLite para desarrollo local; PostgreSQL 18 opcional con puerto configurable
- psycopg 3, django-axes, openpyxl, python-dotenv
- Plantillas Django, CSS propio y JavaScript mínimo (sin frameworks de frontend)

## Requisitos previos (Windows)

- [Python 3.13](https://www.python.org/downloads/) (marque "Add python.exe to PATH" al instalar)
- [Docker Desktop](https://www.docker.com/products/docker-desktop/) si va a usar PostgreSQL con Docker

## Instalación en Windows (PowerShell)

1. Abra la carpeta local del proyecto:

   ```powershell
   cd C:\Suministros
   ```

2. Cree y active el entorno virtual:

   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

   Si PowerShell bloquea el script de activación, habilítelo solo para esta ventana y vuelva a activar:

   ```powershell
   Set-ExecutionPolicy -Scope Process Bypass
   .\.venv\Scripts\Activate.ps1
   ```

   Si tiene varias versiones de Python, use `py -3.13 -m venv .venv` (o, con uv, `uv venv --python 3.13 --seed .venv`).

3. Instale las dependencias:

   ```powershell
   pip install -r requirements.txt
   ```

4. Cree el archivo de configuración y complételo:

   ```powershell
   copy .env.example .env
   ```

   Genere la clave secreta con el siguiente comando y péguela en `DJANGO_SECRET_KEY`:

   ```powershell
   python -c "import secrets; print(secrets.token_urlsafe(50))"
   ```

   Para desarrollo local defina `DJANGO_DEBUG=True`,
   `DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1` y `DJANGO_BASE_DATOS=sqlite`.
   Si usa PostgreSQL, seleccione `DJANGO_BASE_DATOS=postgresql` y complete
   `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` y `POSTGRES_PORT`.

5. Si eligió PostgreSQL, inícielo (omita este paso con SQLite):

   ```powershell
   docker compose up -d
   ```

   La contraseña de PostgreSQL se fija la primera vez que se crea el volumen `datos_postgres`.
   Si después la cambia en `.env`, debe recrear el volumen (`docker compose down -v`, que **borra los datos**).

6. Cree las tablas y el usuario administrador:

   ```powershell
   python manage.py migrate
   python manage.py createsuperuser
   ```

   `createsuperuser` pide el correo y el nombre; el superusuario queda con rol desarrollador.

7. Ejecute las pruebas:

   ```powershell
   python manage.py test
   ```

8. Inicie el servidor de desarrollo y abra http://127.0.0.1:8001/ingresar/ (ingreso con su correo;
   el administrador técnico, solo para desarrolladores, está en http://127.0.0.1:8001/admin/):

   ```powershell
   python manage.py runserver 127.0.0.1:8001
   ```

## Problemas frecuentes

- **"ports are not available ... 5433"** al ejecutar `docker compose up -d`: otro programa
  (por ejemplo, un PostgreSQL instalado directamente en Windows) ya usa el puerto 5433.
  Detenga ese servicio o cambie `POSTGRES_PORT` en `.env` por un puerto libre (por ejemplo, 5434);
  Django y Docker leen el mismo valor.
- **"Falta la variable de entorno ..."**: revise que el archivo `.env` exista y tenga ese valor.

## Configuración

El entorno local usa SQLite de forma predeterminada. Para usar PostgreSQL con Docker,
defina `DJANGO_BASE_DATOS=postgresql` en `.env` antes de ejecutar las migraciones.
En producción PostgreSQL es el motor predeterminado. Cambiar de motor no transfiere
los datos: requiere una migración de datos independiente.

Todas las variables están documentadas en [.env.example](.env.example). El archivo `.env`
nunca se sube al repositorio.

Con `DJANGO_PRODUCCION=True` se activan la redirección a HTTPS, las cookies seguras y HSTS.
Se exige `DJANGO_DEBUG=False` y `DJANGO_ALLOWED_HOSTS` definido. Verifique con:

```powershell
python manage.py check --deploy
```

## Seguridad de cuentas

- **Ingreso:** se ingresa con correo y clave. Tras 5 intentos fallidos, ese correo queda bloqueado
  15 minutos (django-axes).
- **Sesión:** se cierra tras 30 minutos sin actividad y al cerrar el navegador.
- **Claves:** mínimo 10 caracteres; no pueden parecerse al correo o al nombre, ser comunes ni ser
  solo números.
- **Cambio obligatorio:** si un usuario tiene marcado "debe cambiar la clave" (por ejemplo, tras recibir
  una clave asignada), el sistema solo le permite cambiarla o cerrar sesión.
- **Bitácora:** los cambios de usuarios, áreas y claves quedan en una bitácora de solo inserción, con
  motivo obligatorio. Ni siquiera la base de datos permite modificar o borrar sus registros.

## Configuración del sistema

Los administradores y desarrolladores administran áreas, coordinadores, unidades de medida, productos
sugeridos y usuarios en http://127.0.0.1:8000/configuracion/. Nada se borra: se desactiva, y cada cambio
pide un motivo que queda en la bitácora. Solo un desarrollador puede crear o modificar desarrolladores.

## Importar una proyección desde Excel

Abra una proyección editable y seleccione **Importar líneas desde Excel**.
Descargue la plantilla, diligencie las unidades por abreviatura y cargue el `.xlsx`.
Revise los errores y confirme las filas válidas con un motivo, eligiendo agregar
o reemplazar las líneas existentes. La vista previa vence en 30 minutos y no guarda
líneas hasta confirmar. Las proyecciones aprobadas se modifican mediante ajustes.

Consulte [el estado de los 45 prompts](docs/estado_prompts.md) para continuar el desarrollo.

## Catálogo de proveedores y FR-GDS-14

En **Configuración → Catálogos de proveedores** puede administrar categorías,
tipos de documento, requisitos FR-GDS-14 y pesos de 1 o 2 por categoría. Cada
cambio exige un motivo y conserva su historial; los catálogos se desactivan.

La [guía de carga CSV](docs/ejemplos/fr14_csv.md) explica el comando `cargar_fr14`
y el ejemplo ficticio de 26 requisitos. Los textos oficiales están pendientes
de entrega y aprobación de la clínica.

## PostgreSQL en Windows con una DLL bloqueada

Si el Control de aplicaciones de Windows bloquea `psycopg_binary`, puede ejecutar
psycopg con su implementación Python y la biblioteca instalada con PostgreSQL:

```powershell
$env:PSYCOPG_IMPL = "python"
$env:PATH = "C:\Program Files\PostgreSQL\18\bin;" + $env:PATH
$env:DJANGO_BASE_DATOS = "postgresql"
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py test
```

Adapte la ruta a su instalación. Esto mantiene la política de Windows; las
credenciales siguen leyéndose de `.env`. Se verificó la conexión con PostgreSQL 18.6.

## Portal de proveedores

Los proveedores pueden registrarse en `/portal/registro/` desde el enlace del ingreso.
En `/portal/` consultan su ficha, envían PDF para revisión y descargan sus propios
documentos. La activación inicial de la cuenta se configura en el parámetro
`portal.activar_cuenta_al_registrar` (Sí por defecto).

La [guía del portal](docs/portal_proveedores.md) describe el uso, los permisos y
los requisitos antes de publicarlo en internet. Administración revisa los envíos en
**Proveedores → Bandeja de envíos**, donde también puede registrar PDF recibidos
por otros medios. La [guía de la bandeja](docs/bandeja_envios.md) explica aceptación,
descarte y retención de archivos.

## Versiones FR-GDS-14 y evaluaciones

En **Proveedores → Matrices FR-GDS-14** puede copiar y publicar matrices. El
catálogo anterior queda en la versión 1 en borrador. Las versiones publicadas se
conservan y cada evaluación mantiene la categoría y la versión usadas.
Desde una ficha de proveedor seleccione **Nueva evaluación FR-GDS-14**.
Consulte la [guía de matrices](docs/matrices_fr14.md). Desde el detalle de cada
evaluación puede responder los requisitos y vincular documentos o PDF privados;
la [guía de respuestas](docs/respuestas_fr14.md) explica confirmación de N/A,
avance y trazabilidad. La [guía de cálculo](docs/calculo_fr14.md) explica las reglas
D-06 configurables, el resultado provisional y la finalización con resultados
conservados. La fórmula y los umbrales iniciales requieren aprobación de la clínica.

La ficha del proveedor muestra el historial y su última evaluación finalizada no
anulada. Desde el detalle puede anular con motivo o copiar a un borrador independiente;
se conservan los resultados y evidencias originales. Consulte la
[guía de historial y copias](docs/historial_evaluaciones.md).

En Configuración → Catálogos de proveedores → Documentos exigidos puede definir
las exigencias D-05 por categoría y requisito. La ficha y la evaluación muestran
faltantes, vencidos, próximos y vigentes. El modo predeterminado advierte al responder
Sí con evidencia vencida; puede activar el bloqueo mediante parámetros. La lista
oficial no se carga automáticamente. Consulte la [guía documental](docs/control_documental.md).

## Necesidades y listas de elegibles FR-GDS-20

En **Compras → Nueva necesidad** puede registrar el objeto de la compra, área,
fecha y origen. Puede tomar cantidades de líneas aprobadas de proyecciones o
describir un origen manual, con tipos configurables. Desde la necesidad cree
listas en borrador y agregue o retire proveedores con motivo y bitácora.
Los participantes conservan la identidad por NIT sin duplicados. La política de
reserva de cantidades D-09 está pendiente. Consulte la
[guía de necesidades y elegibles](docs/necesidades_elegibles.md).

En **Compras → Criterios FR-GDS-20** puede editar y publicar versiones de criterios
cuyos pesos sumen 100 %. Desde cada lista abra **Calificaciones y puntajes** para
registrar cumplimiento y observación, con subtotales explicados y totales Decimal.
La escala inicial 5/3/1 y el método directo son provisionales D-07; escala y método
se conservan por lista. Consulte la [guía de calificación](docs/calificacion_elegibles.md).
En **Puestos y decisión** puede distribuir cantidades, justificar proveedor único
y elecciones excepcionales, registrar desempates y exportar a Excel. Los cambios
de calificaciones o participantes exigen revisar la decisión. D-08 sigue pendiente
de aprobación. Consulte la [guía de decisión](docs/decision_elegibles.md).
Desde **Evaluación FR14 y estado documental** consulte la calificación vigente y
las alertas de cada participante, configure advertencia/bloqueo y registre la
justificación para proveedores elegidos. La antigüedad inicial de doce meses es
provisional. La [guía del vínculo documental](docs/vinculo_documental_elegibles.md)
describe reglas y foto histórica. Desde el detalle de la lista puede cerrar,
reabrir o anular con motivo, y consultar el historial de cada cierre. Cerrar conserva
resultados y documentos; no crea cotizaciones ni órdenes. **Iniciar cotización**
abre el formulario precargado desde el cierre; solo crea el registro al guardar.
Consulte la [guía de cierres y transición](docs/cierres_elegibles.md).

En **Cotizaciones** puede registrar el encabezado FR-GDS-28 y especificaciones con
cantidad y unidad, manualmente o desde una lista cerrada. Los tipos son configurables
y cada registro recibe un consecutivo interno. Los límites D-10 iniciales de tres
invitados y diez líneas son editables; 0 elimina el límite de negocio. Consulte la
[guía de cotizaciones](docs/cotizaciones.md).

Desde cada proveedor invitado puede registrar o actualizar su **oferta**, con
precios por línea, tarifas configurables, totales Decimal y PDF privado opcional.
Cada guardado conserva una revisión y sus evidencias anteriores. El redondeo D-11
es configurable; no se supone IVA fijo. Consulte la [guía de ofertas](docs/ofertas.md).

En **Verificaciones** puede revisar la matriz por oferente, registrar estados con
responsable y fecha y conservar evidencias PDF privadas. Los controles y su
obligatoriedad son configurables. La propuesta documental requiere confirmación
expresa; Sarlaft/Sicof se registran manualmente. Consulte la
[guía de verificaciones](docs/verificaciones_ofertas.md).

Desde **Proveedor único y justificación** puede confirmar el caso con causal,
texto y evidencia privada. Se sugiere si hay una sola oferta; el mínimo de caracteres
y la obligatoriedad del PDF son configurables. Cada cambio conserva motivo e historial.
Consulte la [guía de proveedor único](docs/proveedor_unico_cotizacion.md).

En **Comparativo y decisión** puede comparar precios, impuestos, verificaciones y
puntaje de elegibles de origen, adjudicar una oferta completa o por línea y proponer
la compra. Las aprobaciones distintas son configurables; al completarse, se conserva
la decisión y la cotización queda en solo lectura. Los cambios requieren anulación
con motivo. Puede exportar la comparación y sus decisiones históricas a Excel.
Consulte la [guía de decisión de cotización](docs/decision_cotizacion.md).

Si la compra requiere contrato, indíquelo antes de proponer la decisión. Desde la
propuesta registre supervisor, vigencia, pago, valor y pólizas con evidencias privadas.
Los campos obligatorios son configurables y se validan antes de aprobar; las firmas
conservan su foto contractual. Consulte la [guía de contratos y pólizas](docs/contratos_polizas.md).

Desde una decisión aprobada puede crear **órdenes de compra en borrador**, una por
proveedor adjudicado, con copia de lo acordado y vínculos al origen. Repetir la creación
no duplica órdenes. Las ediciones conservan original, cambios y motivo; anular la
decisión anula sus borradores con historial. Consulte la [guía de órdenes](docs/ordenes_compra.md).

La [guía de consecutivos](docs/consecutivos_ordenes.md) explica el motor de numeración
al emitir: prefijo, año, longitud y reinicio anual configurables, con protección de
concurrencia y anulación sin reutilizar números. Los borradores incluyen fecha de
validez opcional con etiqueta configurable. La emisión desde la interfaz requiere las aprobaciones del ciclo vigente. Los borradores admiten descuentos por línea, tarifas y retenciones con
base mínima, reglas de cálculo guardadas y desglose. Consulte la
[guía de importes](docs/importes_ordenes.md).

Las órdenes se aprueban por personas distintas del elaborador (configurable), generan
un PDF FR-GDS-21 directamente y admiten evidencia privada de envío. Configure antes
el nombre y NIT de la clínica en Parámetros. Las recepciones, ajustes y devoluciones
conservan cantidades y responsables; los excesos requieren autorización expresa.

**Seguimientos** reúne origen, eventos, entregas, hitos, saldos, cierre/reapertura y
reportes Excel. **Listados** y la búsqueda superior permiten filtrar por módulo, NIT
y consecutivo. Consulte la [guía de aprobación, recepción y seguimiento](docs/aprobacion_recepcion_seguimientos.md).

La [guía de despliegue Ubuntu](docs/despliegue.md) incluye plantillas Gunicorn/nginx,
entorno de producción sin secretos y respaldo/restauración con retención configurable.
La VM y los certificados reales siguen pendientes; no se ha publicado el sistema.

## Archivos privados

Los PDF subidos se guardan en `archivos_privados/` (fuera del repositorio) y **no** se publican
por URL. Solo se descargan mediante vistas que validan los permisos del usuario.

## Convenciones

- Interfaz en español, tratando al usuario de "usted".
- Finales de línea CRLF (definidos en `.gitattributes`).
- Etiquetas `{% %}` de Django completas en una sola línea (lo verifica una prueba).
- Solo datos ficticios en código, pruebas y ejemplos (correos `@ejemplo.test`).

El avance del proyecto se registra en [docs/avances.md](docs/avances.md).
