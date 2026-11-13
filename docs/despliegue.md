# B28 · Despliegue en Ubuntu Server 24.04

Esta entrega prepara archivos y procedimientos; la máquina virtual todavía no
existe. No se ha publicado el sistema ni instalado servicios en otro equipo.
Los dominios y datos de esta guía son ficticios. No copie el `.env`, la base SQLite
ni las cuentas de desarrollo al servidor de producción.

## Preparar usuario, Python y código

Ejecute como operador autorizado en la VM. Cree un usuario sin ingreso interactivo,
carpetas para código, estáticos y documentos privados, y herramientas de instalación:

```bash
sudo apt update
sudo apt install -y python3-venv nginx postgresql-common
sudo useradd --system --create-home --home-dir /srv/suministros --shell /usr/sbin/nologin suministros
sudo install -d -o suministros -g suministros -m 750 /srv/suministros/app /srv/suministros/privados
sudo install -d -o suministros -g www-data -m 755 /srv/suministros/static
sudo install -d -o root -g suministros -m 750 /etc/suministros
sudo install -d -o suministros -g suministros -m 700 /var/backups/suministros
sudo -u suministros python3 -m venv /srv/suministros/herramientas
sudo -u suministros /srv/suministros/herramientas/bin/pip install uv
sudo -u suministros /srv/suministros/herramientas/bin/uv python install 3.13.15
```

Copie una entrega revisada a `/srv/suministros/app`, sin `.env`, `.venv`, bases,
archivos privados ni respaldos del equipo de desarrollo. Ajuste su propietario a
`suministros:suministros`. Cree el entorno e instale las dependencias fijadas:

```bash
cd /srv/suministros/app
sudo -u suministros /srv/suministros/herramientas/bin/uv venv --python 3.13.15 .venv
sudo -u suministros /srv/suministros/herramientas/bin/uv pip install --python .venv/bin/python -r requirements.txt
```

Ubuntu 24.04 no se da por supuesto con Python 3.13 instalado. La guía de
[instalación de Python con uv](https://docs.astral.sh/uv/guides/install-python/)
explica la selección explícita del intérprete. Gunicorn se instala en Linux mediante
el marcador de plataforma de `requirements.txt`; se mantiene `runserver` para desarrollo.

## PostgreSQL 18

Configure el repositorio oficial y las herramientas de servidor y respaldo:

```bash
sudo /usr/share/postgresql-common/pgdg/apt.postgresql.org.sh
sudo apt update
sudo apt install -y postgresql-18 postgresql-client-18
sudo -u postgres createuser --pwprompt suministros
sudo -u postgres createdb --owner=suministros suministros
```

Use una contraseña nueva y guárdela únicamente en el archivo de entorno protegido.
El usuario de la aplicación no necesita ser superusuario ni crear bases en producción.
Mantenga PostgreSQL escuchando localmente. La
[guía oficial para Ubuntu](https://www.postgresql.org/download/linux/ubuntu/)
documenta el repositorio y los paquetes por versión. Use `pg_dump`/`pg_restore` de la
misma versión principal que el servidor; no use el cliente 16 para respaldar un servidor 18.

Como alternativa puede usar `docker-compose.yml` con PostgreSQL 18 y volumen
persistente. Instale Docker siguiendo su documentación, utilice `--env-file` con el
archivo protegido y conserve la publicación del puerto en `127.0.0.1`. En ese caso
ajuste `POSTGRES_PORT` al puerto del host y mantenga también el cliente PostgreSQL 18
para los respaldos del servicio.

## Entorno sin secretos en el repositorio

Copie `.env.produccion.example` a `/etc/suministros/suministros.env`, propietario
`root:suministros`, permisos `640`. El archivo entregado contiene solo nombres de
variables. Complete los valores directamente en el servidor:

| Variable | Valor a configurar |
| --- | --- |
| `DJANGO_SECRET_KEY` | Clave aleatoria nueva, extensa y exclusiva del servidor |
| `DJANGO_DEBUG` | `False` |
| `DJANGO_PRODUCCION` | `True` |
| `DJANGO_ALLOWED_HOSTS` | Dominio real, sin comodines |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | `https://` seguido del dominio real |
| `DJANGO_DETRAS_DE_PROXY` | `True` con el nginx de esta entrega como único proxy |
| `DJANGO_BASE_DATOS` | `postgresql` |
| `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` | Credenciales creadas para esta instalación |
| `POSTGRES_HOST`, `POSTGRES_PORT` | `127.0.0.1` y el puerto real del servidor |
| `DJANGO_ARCHIVOS_PRIVADOS` | `/srv/suministros/privados` |
| `DJANGO_STATIC_ROOT` | `/srv/suministros/static` |
| `DJANGO_HSTS_SEGUNDOS` | `3600` al comenzar; elevar a `31536000` tras estabilizar HTTPS |
| `DJANGO_HSTS_SUBDOMINIOS`, `DJANGO_HSTS_PRELOAD` | Solo activar tras revisar HTTPS de todos los subdominios y la política de precarga |
| `SUMINISTROS_BACKUP_DIR` | `/var/backups/suministros` |
| `SUMINISTROS_RESPALDOS_DIARIOS`, `SUMINISTROS_RESPALDOS_SEMANALES` | Inicialmente `7` y `4`, sujetos a la política aprobada |

`DJANGO_ENV_FILE` permite indicar ese archivo al ejecutar comandos. Las variables
ya presentes en el entorno tienen prioridad sobre las del archivo; no se hace
`source` del archivo como código de shell.

```bash
cd /srv/suministros/app
sudo -u suministros env DJANGO_ENV_FILE=/etc/suministros/suministros.env .venv/bin/python manage.py migrate --noinput
sudo -u suministros env DJANGO_ENV_FILE=/etc/suministros/suministros.env .venv/bin/python manage.py collectstatic --noinput
sudo -u suministros env DJANGO_ENV_FILE=/etc/suministros/suministros.env .venv/bin/python manage.py createsuperuser
sudo -u suministros env DJANGO_ENV_FILE=/etc/suministros/suministros.env .venv/bin/python manage.py check --deploy
```

Cree las cuentas administrativas desde la interfaz con contraseñas nuevas. Configure
nombre y NIT reales de la clínica, categorías, impuestos, retenciones, reglas de
aprobación y política de recepción con los responsables correspondientes. Las tasas,
SLA y decisiones pendientes no se consideran aprobados por instalar el sistema.

## Gunicorn, nginx y HTTPS

Revise `deploy/gunicorn.service` y cópielo a
`/etc/systemd/system/suministros.service`. Escucha solo en `127.0.0.1:8002`, usa el
usuario del servicio, toma el entorno protegido y escribe únicamente en documentos
privados. Los registros van al journal:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now suministros
sudo systemctl status suministros
sudo journalctl -u suministros -n 100 --no-pager
```

En `deploy/nginx.conf`, sustituya el dominio ficticio y las rutas del certificado.
Puede usar el certificado de la clínica o Let's Encrypt cuando exista un dominio
público verificable. Instale primero un certificado válido y después habilite el
servidor TLS. Copie la configuración a `sites-available`, habilítela en `sites-enabled`
y compruebe `sudo nginx -t` antes de recargar nginx.

Nginx sirve únicamente `/srv/suministros/static/`; no tiene un alias para documentos
privados ni para todo el árbol de la aplicación. Las rutas `/privados/`,
`/archivos_privados/` y archivos ocultos se rechazan. Los PDF se entregan mediante
Django tras verificar permisos. Conserve los directorios privados con modo `750`
y propietario `suministros:suministros`; nginx no necesita pertenecer a ese grupo.
Mantenga el límite de carga coherente con los PDF de 10 MB admitidos por la aplicación.

Revise las guías de [Gunicorn con proxy](https://gunicorn.org/deploy/) y la
[lista de despliegue de Django 5.2](https://docs.djangoproject.com/en/5.2/howto/deployment/checklist/).
El valor de `X-Forwarded-For` se sustituye en el proxy de confianza, evitando confiar
en un valor enviado directamente por el cliente.

## Respaldo, retención y responsables

Complete antes de habilitar la programación:

| Dato operativo | Valor aprobado por la clínica |
| --- | --- |
| Responsable y suplente | Pendiente |
| Frecuencia y ventana de mantenimiento | Pendiente |
| Retención diaria / semanal | Provisional: 7 / 4 |
| Copia fuera del servidor y cifrado | Pendiente |
| Tiempo de recuperación esperado | Pendiente |
| Fecha y responsable del último ensayo de restauración | Pendiente |

`deploy/respaldo.sh` impide ejecuciones simultáneas y llama a `deploy/respaldo.py`.
Este usa `pg_dump --format=custom`, incluye los archivos privados en un `.tar.gz`,
calcula SHA-256 por archivo y verifica el paquete antes de publicarlo. Guarda un
diario por fecha y, los domingos, un semanal por semana ISO; rota únicamente los
archivos de respaldo de la carpeta indicada. Las credenciales se transmiten por
entorno a las herramientas, sin ponerlas en la línea de comandos o el manifiesto.

Para una copia conjunta coherente de base y archivos, use la ventana de mantenimiento
con el servicio detenido. No hace falta detener PostgreSQL:

```bash
sudo systemctl stop suministros
sudo -u suministros bash /srv/suministros/app/deploy/respaldo.sh
sudo systemctl start suministros
sudo -u suministros /srv/suministros/app/.venv/bin/python /srv/suministros/app/deploy/respaldo.py --verificar /var/backups/suministros/diario-AAAA-MM-DD.tar.gz
```

Si el respaldo falla, revise el error y vuelva a iniciar el servicio después de
resolverlo; no trate un archivo parcial como respaldo válido. El nombre final solo
se publica tras verificarlo. Programe la tarea con el responsable y horario aprobados;
no se ha creado una tarea en el equipo del usuario ni en un servidor externo.

## Restauración y ensayo

Ensaye primero en otra base y otra carpeta privada, con un archivo de entorno de
pruebas que señale esos destinos. No pruebe la restauración sobre producción.

1. Verifique el paquete con `--verificar` y registre fecha, responsable y checksum.
2. En un ensayo, cree una base vacía con el propietario de la aplicación y configure
   `POSTGRES_DB` con ese nombre y `DJANGO_ARCHIVOS_PRIVADOS` con una carpeta de ensayo.
3. Confirme los destinos leyendo el archivo de entorno sin mostrar sus contraseñas.
4. Ejecute la restauración con el servicio de destino detenido:

```bash
cd /srv/suministros/app
sudo -u suministros env DJANGO_ENV_FILE=/etc/suministros/restauracion-prueba.env .venv/bin/python deploy/respaldo.py --restaurar /var/backups/suministros/diario-AAAA-MM-DD.tar.gz --confirmar-sustitucion
sudo -u suministros env DJANGO_ENV_FILE=/etc/suministros/restauracion-prueba.env .venv/bin/python manage.py migrate --check
sudo -u suministros env DJANGO_ENV_FILE=/etc/suministros/restauracion-prueba.env .venv/bin/python manage.py check
```

5. Verifique ingreso, un proveedor, una orden y sus firmas, una recepción y un PDF
   privado. Compare conteos y sumas con el origen del ensayo.
6. Para recuperar producción, haga primero un respaldo de su estado actual y detenga
   el servicio. Use el entorno de producción solo tras revisar los destinos. La
   opción `--confirmar-sustitucion` permite sustituir la base: no omitir esa revisión.
7. Restaure sobre una carpeta privada vacía de recuperación y ajuste su ruta en el
   entorno. El restaurador copia los archivos del paquete; no borra archivos ajenos
   que ya existan en la carpeta de destino. Conserve la carpeta anterior como respaldo.
8. Ajuste permisos `750` de directorios y propietario, compruebe migraciones,
   `check --deploy`, HTTPS y PDF, y después inicie el servicio.

El restaurador exige que el paquete incluya la base declarada, un manifiesto válido,
hashes SHA-256 y cabecera del formato correspondiente (SQLite o PostgreSQL custom).
Rechaza paquetes incompletos, rutas fuera del paquete, enlaces, nombres duplicados,
checksums incorrectos y cambios de motor antes de sustituir la base de destino.
SQLite se abre en modo de solo lectura y se comprueba su integridad antes de abrir
el destino para restaurarlo. PostgreSQL se restaura con
`pg_restore --clean --if-exists --single-transaction --exit-on-error`. Las pruebas
automatizadas incluyen ida y vuelta de base y archivo PDF en SQLite y, al ejecutar
la suite PostgreSQL, en dos bases ficticias aisladas. Esto no sustituye el ensayo
completo de la VM con el certificado y permisos reales.

## Antes de habilitar usuarios reales

- `DEBUG=False`, hosts exactos, clave nueva y archivo de entorno protegido.
- PostgreSQL y Gunicorn no publicados directamente en la red.
- HTTPS válido, CSRF del dominio real y cookies seguras; HSTS comienza en `3600`.
- Revisar subdominios y precarga antes de habilitar sus indicadores. Para una
  comprobación estricta sin advertencias de HSTS, ambas decisiones deben estar
  resueltas. No silenciar advertencias para aparentar una validación.
- `check --deploy --fail-level WARNING` sin advertencias activas con la política final.
  Se ha ejecutado con un entorno temporal ficticio de producción y ambos indicadores
  HSTS activados, sin cambiar el `.env` local. La exclusión previa `axes.W006` se
  conserva; no se agregaron exclusiones para ocultar resultados de esta comprobación.
- Migraciones y estáticos aplicados; descarga pública de PDF rechazada.
- Nombre/NIT de clínica y decisiones D-01 a D-17 revisados por sus responsables.
- Respaldo fuera del árbol servido, retención aprobada y restauración ensayada.
- Validar `nginx -t`, systemd, carga y HTTPS en la VM; estas comprobaciones de Linux
  quedan pendientes porque el entorno de trabajo actual es Windows.
