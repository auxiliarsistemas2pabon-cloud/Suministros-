"""Carga un FR11 exclusivamente en la base local de demostración."""
from datetime import date
from decimal import Decimal
import json
from pathlib import Path
import secrets
import shutil

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.urls import reverse

from areas.models import Area
from bitacora.servicios import guardar_con_bitacora, registrar
from cuentas.models import Rol, Usuario
from cuentas.servicios import guardar_usuario
from proyecciones import servicios
from proyecciones.fr11_origen import leer_consolidado
from proyecciones.models import CAMPOS_CANTIDADES_MENSUALES, Linea, Periodo, ProyeccionArea, UnidadMedida

MOTIVO = "Ejemplo solicitado a partir de FR-GDS-11 2026; operaciones posteriores ficticias en base separada."


def comprobar_entorno():
    esperado = (settings.BASE_DIR / ".demostracion" / "db_demo.sqlite3").resolve()
    configurado = Path(connection.settings_dict["NAME"]).resolve()
    if not getattr(settings, "MODO_DEMOSTRACION", False) or configurado != esperado:
        raise CommandError("Este comando solo funciona con --settings=config.settings_demo y su base separada.")


class Command(BaseCommand):
    help = "Prepara un ejemplo local completo desde un consolidado FR11 sin cargarlo en la base principal."

    def add_arguments(self, parser):
        parser.add_argument("archivo", type=Path)
        parser.add_argument("--equis-como-unidad", action="store_true", help="Interpretación confirmada de x = 1.")
        parser.add_argument("--unidad-provisional", action="store_true", help="Usar unidad de forma provisional, por indicación del usuario.")
        parser.add_argument("--recorrido", action="store_true", help="Añadir la compra y recepción ficticias para explicar el proceso.")

    def handle(self, *args, **options):
        comprobar_entorno()
        if not options["unidad_provisional"]:
            raise CommandError("Confirme --unidad-provisional o complete las unidades antes de cargar el ejemplo.")
        archivo = options["archivo"].resolve()
        if not archivo.is_file():
            raise CommandError("No existe el consolidado indicado.")
        directorio = settings.DIRECTORIO_DEMOSTRACION
        manifiesto = directorio / "recorrido.json"
        if manifiesto.exists():
            raise CommandError("El ejemplo ya existe. No se sobrescribieron sus datos ni se duplicó la carga.")
        if Usuario.objects.exists() or Area.objects.exists() or Periodo.objects.exists():
            raise CommandError("La base demo contiene datos. Use una base demo nueva para no mezclarlos.")
        with archivo.open("rb") as fuente:
            previa = leer_consolidado(fuente, equis_como_unidad=options["equis_como_unidad"])
        if not previa["areas"]:
            raise CommandError("No se encontraron áreas para el ejemplo.")
        if previa.get("costo_proyectado_total") is None:
            raise CommandError("Hay costos sin resolver; revise el archivo antes de cargar el ejemplo.")
        clave = "Demo-" + secrets.token_urlsafe(12) + "!"
        accesos = []

        def usuario(correo, nombre, rol, area=None, tecnico=False):
            persona = Usuario(correo=correo, nombre=nombre, rol=rol, area=area,
                activo=True, debe_cambiar_clave=False, is_staff=tecnico, is_superuser=tecnico)
            persona.set_password(clave)
            guardar_usuario(persona, actor=admin if accesos else persona, motivo=MOTIVO)
            accesos.append({"correo": correo, "nombre": nombre, "rol": persona.get_rol_display()})
            return persona

        # Todas las escrituras de negocio se agrupan. Un fallo no deja un ejemplo a medias.
        with transaction.atomic():
            # El primer actor todavía no tiene PK: se crea y luego se audita a sí mismo.
            admin = Usuario.objects.create_user(correo="admin@demostracion.local", password=clave,
                nombre="Administrador del ejemplo", rol=Rol.ADMINISTRADOR, debe_cambiar_clave=False)
            registrar("usuario.creado", actor=admin, objeto=admin, motivo=MOTIVO)
            accesos.append({"correo": admin.correo, "nombre": admin.nombre, "rol": admin.get_rol_display()})
            aprobador = usuario("aprobador@demostracion.local", "Aprobador del ejemplo", Rol.ADMINISTRADOR)
            usuario("soporte@demostracion.local", "Soporte del ejemplo", Rol.DESARROLLADOR, tecnico=True)
            for indice, datos_area in enumerate(previa["areas"], 1):
                area = Area(nombre=datos_area["nombre"], codigo_area=f"DEM-{indice:02}")
                area.full_clean()
                guardar_con_bitacora(area, ["nombre", "codigo_area", "activa"], actor=admin,
                    motivo=MOTIVO, accion_crear="area.creada", accion_modificar="area.modificada")
                datos_area["area_id"] = area.pk
                persona = usuario(f"area{indice}@demostracion.local", (f"Coordinación {area.nombre}")[:150], Rol.COORDINADOR, area)
                datos_area["coordinador_id"] = persona.pk
            unidad = UnidadMedida(nombre="Unidad provisional del ejemplo", abreviatura="und-demo")
            servicios.guardar_unidad(unidad, actor=admin, motivo=MOTIVO)
            periodo = servicios.abrir_periodo(previa["anio"], date(previa["anio"], 12, 31), actor=admin,
                motivo=MOTIVO, fecha_apertura=date(previa["anio"], 1, 1))
            for datos_area in previa["areas"]:
                proyeccion = ProyeccionArea.objects.get(periodo=periodo, area_id=datos_area["area_id"])
                datos_area["proyeccion_id"] = proyeccion.pk
                datos_area["url_revision"] = reverse("proyecciones:revision_detalle", args=[proyeccion.pk])
                cargadas = []
                for datos_linea in datos_area["lineas"]:
                    if not datos_linea["importable"]:
                        continue
                    valores = dict(zip(CAMPOS_CANTIDADES_MENSUALES, datos_linea["meses"]))
                    linea = Linea(proyeccion=proyeccion, producto_servicio=datos_linea["producto_servicio"],
                        dependencia=datos_linea["dependencia"], unidad=unidad,
                        precio_estimado=Decimal(datos_linea["precio_estimado_referencial"] or "0"),
                        costo_proyectado_total=Decimal(datos_linea["costo_proyectado_total"]), **valores)
                    servicios.guardar_linea(linea, actor=admin, motivo=MOTIVO)
                    datos_linea["linea_id"] = linea.pk
                    cargadas.append(linea.costo_anual)
                datos_area["costo_cargado"] = str(sum(cargadas, Decimal("0")))
            registrar("demostracion.consolidado_cargado", actor=admin, objeto=periodo, motivo=MOTIVO,
                nuevo={"fuente_sha256": previa["archivo_sha256"], "areas": len(previa["areas"]),
                    "lineas_cargadas": Linea.objects.count(), "cantidades_pendientes": previa.get("lineas_pendientes")})
        # Los PDF privados usan transacciones durables propias: el recorrido no
        # se anida dentro de la transacción de importación de proyecciones.
        operacion = {}
        if options["recorrido"]:
            from config.demo.recorrido import crear_recorrido
            from django.utils import timezone
            elegida = Linea.objects.filter(producto_servicio__iexact="EQUIPOS DE COMPUTO AIO").select_related("proyeccion__area").first()
            if elegida is None:
                raise CommandError("No se encontró la línea AIO acordada para el recorrido; no se inventó otra selección.")
            proyeccion = elegida.proyeccion
            coordinador = Usuario.objects.get(rol=Rol.COORDINADOR, area=proyeccion.area)
            proyeccion.estado = ProyeccionArea.Estado.ENVIADA
            proyeccion.fecha_envio = timezone.now()
            proyeccion.enviado_por = coordinador
            servicios.guardar_proyeccion_area(proyeccion, actor=coordinador, motivo=MOTIVO,
                accion_modificar="proyeccion_area.enviada", permitir_envio=True)
            servicios.aprobar_proyeccion(proyeccion, actor=aprobador, cantidades={elegida.pk: 4}, motivo=MOTIVO)
            elegida.refresh_from_db()
            operacion = crear_recorrido(usuarios={"admin": admin, "aprobador": aprobador, "coordinador": coordinador},
                linea=elegida, carpeta_salida=directorio)
            for persona in Usuario.objects.filter(rol=Rol.PROVEEDOR):
                persona.set_password(clave)
                guardar_usuario(persona, actor=admin, motivo=MOTIVO)
                accesos.append({"correo": persona.correo, "nombre": persona.nombre, "rol": persona.get_rol_display()})
        directorio.mkdir(parents=True, exist_ok=True)
        (directorio / "fuente").mkdir(exist_ok=True)
        shutil.copy2(archivo, directorio / "fuente" / archivo.name)
        for area in previa["areas"]:
            area["estado"] = ProyeccionArea.objects.get(pk=area["proyeccion_id"]).get_estado_display()
        previa.update({"archivo_nombre": archivo.name, "accesos": accesos, "operacion": operacion,
            "costo_cargado": str(sum((Decimal(a["costo_cargado"]) for a in previa["areas"]), Decimal("0"))),
            "url_consolidado": reverse("proyecciones:consolidado") + f"?anio={previa['anio']}"})
        manifiesto.write_text(json.dumps(previa, ensure_ascii=False, indent=2), encoding="utf-8")
        (directorio / "accesos.local.json").write_text(json.dumps({"clave": clave, "cuentas": accesos},
            ensure_ascii=False, indent=2), encoding="utf-8")
        self.stdout.write(self.style.SUCCESS(f"Ejemplo preparado: {Linea.objects.count()} líneas; {len(previa['areas'])} áreas."))
        self.stdout.write("Abra http://127.0.0.1:8002/ejemplo/ e ingrese con admin@demostracion.local")
        self.stdout.write("La clave temporal está en .demostracion/accesos.local.json; no se modificaron las cuentas principales.")
