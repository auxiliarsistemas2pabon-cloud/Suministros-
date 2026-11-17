from datetime import date
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError
from django.test import TestCase
from django.urls import reverse
from decimal import Decimal

from areas.models import Area
from bitacora.models import RegistroBitacora
from cuentas.models import Rol
from cuentas.tests.utilidades import crear_area, crear_usuario
from proyecciones.models import (
    CAMPOS_CANTIDADES_MENSUALES,
    Ajuste,
    Linea,
    Periodo,
    ProductoSugerido,
    ProyeccionArea,
    UnidadMedida,
)
from proyecciones.servicios import (
    abrir_periodo,
    cerrar_periodo,
    guardar_linea,
    guardar_producto,
    reabrir_periodo,
)

MOTIVO = "Apertura ficticia autorizada"


class CatalogosTests(TestCase):
    def setUp(self):
        self.unidad = UnidadMedida.objects.create(nombre="  Caja   x 100 ", abreviatura=" cja ")

    def test_normaliza_espacios(self):
        self.assertEqual(self.unidad.nombre, "Caja x 100")
        self.assertEqual(self.unidad.abreviatura, "cja")
        self.assertEqual(str(self.unidad), "Caja x 100 (cja)")

    def test_unicidad_sin_distinguir_mayusculas_en_formulario_y_base(self):
        duplicada = UnidadMedida(nombre="CAJA X 100", abreviatura="CJA")
        with self.assertRaises(ValidationError) as contexto:
            duplicada.full_clean()
        self.assertEqual(set(contexto.exception.message_dict), {"nombre", "abreviatura"})
        with self.assertRaises(IntegrityError), transaction.atomic():
            UnidadMedida.objects.bulk_create([UnidadMedida(nombre="caja x 100", abreviatura="otra")])

    def test_unidad_con_productos_no_se_puede_borrar(self):
        ProductoSugerido.objects.create(nombre="Gasas", unidad_por_defecto=self.unidad)
        with self.assertRaises(ProtectedError):
            self.unidad.delete()

    def test_servicio_rechaza_unidad_inactiva_para_producto_nuevo(self):
        inactiva = UnidadMedida.objects.create(nombre="Galón", abreviatura="gal", activa=False)
        with self.assertRaises(ValidationError) as contexto:
            guardar_producto(ProductoSugerido(nombre="Alcohol", unidad_por_defecto=inactiva), actor=None, motivo="x")
        self.assertIn("unidad_por_defecto", contexto.exception.message_dict)
        self.assertFalse(ProductoSugerido.objects.exists())


class ModelosProyeccionTests(TestCase):
    def setUp(self):
        self.area = crear_area()
        self.usuario = crear_usuario(Rol.ADMINISTRADOR)
        self.unidad = UnidadMedida.objects.create(nombre="Caja", abreviatura="cja")
        self.periodo = Periodo.objects.create(
            anio=2026,
            fecha_apertura=date(2026, 1, 1),
            fecha_limite_diligenciamiento=date(2026, 2, 28),
            creado_por=self.usuario,
        )
        self.proyeccion = ProyeccionArea.objects.create(periodo=self.periodo, area=self.area)

    def linea(self, **cambios):
        valores = {
            "proyeccion": self.proyeccion,
            "producto_servicio": "Guantes de examen",
            "unidad": self.unidad,
            "precio_estimado": Decimal("12.50"),
        }
        valores.update(cambios)
        return Linea(**valores)

    def test_rechaza_cantidad_mensual_negativa(self):
        linea = self.linea(cantidad_enero=-1)
        with self.assertRaises(ValidationError) as contexto:
            linea.full_clean()
        self.assertIn("cantidad_enero", contexto.exception.message_dict)

    def test_rechaza_precio_negativo(self):
        linea = self.linea(precio_estimado=Decimal("-0.01"))
        with self.assertRaises(ValidationError) as contexto:
            linea.full_clean()
        self.assertIn("precio_estimado", contexto.exception.message_dict)

    def test_periodo_area_es_unico(self):
        duplicada = ProyeccionArea(periodo=self.periodo, area=self.area)
        with self.assertRaises(ValidationError) as contexto:
            duplicada.full_clean()
        self.assertTrue(
            any("proyección" in mensaje.lower() for mensaje in contexto.exception.messages)
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            ProyeccionArea.objects.create(periodo=self.periodo, area=self.area)

    def test_calcula_total_y_costo_anual_con_decimal(self):
        linea = self.linea(cantidad_enero=2, cantidad_febrero=3, cantidad_diciembre=1)
        self.assertEqual(linea.total_anual, 6)
        self.assertEqual(linea.costo_anual, Decimal("75.00"))
        self.assertIsInstance(linea.costo_anual, Decimal)

    def test_ajuste_exige_justificacion_y_proyeccion_aprobada(self):
        linea = self.linea()
        linea.save()
        ajuste = Ajuste(
            linea=linea,
            campo="precio_estimado",
            valor_aprobado=Decimal("12.50"),
            valor_nuevo=Decimal("13.00"),
            justificacion="   ",
            usuario=self.usuario,
        )
        with self.assertRaises(ValidationError) as contexto:
            ajuste.full_clean()
        self.assertIn("justificacion", contexto.exception.message_dict)

    def test_servicio_de_linea_registra_bitacora(self):
        linea = self.linea(cantidad_enero=4)
        registro = guardar_linea(linea, actor=self.usuario, motivo="Carga inicial ficticia")
        self.assertEqual(registro.accion, "linea.creada")
        self.assertEqual(registro.actor, self.usuario)
        self.assertEqual(registro.valor_nuevo["cantidad_enero"], 4)


class PeriodosServicioTests(TestCase):
    def setUp(self):
        self.area_activa = crear_area("Farmacia", "FAR")
        self.area_inactiva = crear_area("Laboratorio", "LAB")
        Area.objects.filter(pk=self.area_inactiva.pk).update(activa=False)
        self.administrador = crear_usuario(Rol.ADMINISTRADOR, correo="admin-periodos@ejemplo.test")
        self.coordinador = crear_usuario(
            Rol.COORDINADOR,
            correo="coord-periodos@ejemplo.test",
            area=self.area_activa,
        )
        self.unidad = UnidadMedida.objects.create(nombre="Caja", abreviatura="cja")

    def abrir(self, anio=2026):
        return abrir_periodo(
            anio,
            date(anio, 12, 15),
            actor=self.administrador,
            motivo=MOTIVO,
            fecha_apertura=date(anio, 1, 1),
        )

    def test_abrir_crea_proyeccion_por_area_activa(self):
        periodo = self.abrir()
        self.assertEqual(ProyeccionArea.objects.filter(periodo=periodo).count(), 1)
        self.assertEqual(ProyeccionArea.objects.get(periodo=periodo).area, self.area_activa)
        self.assertFalse(ProyeccionArea.objects.filter(periodo=periodo, area=self.area_inactiva).exists())
        self.assertTrue(RegistroBitacora.objects.filter(accion="periodo.abierto").exists())

    def test_ano_duplicado_rechazado_y_no_crea_otro_periodo(self):
        self.abrir()
        with self.assertRaises(ValidationError) as contexto:
            self.abrir()
        self.assertIn("anio", contexto.exception.message_dict)
        self.assertEqual(Periodo.objects.filter(anio=2026).count(), 1)

    def test_cerrar_y_reabrir_registra_bitacora(self):
        periodo = self.abrir()
        cerrar_periodo(periodo, actor=self.administrador, motivo="Cierre ficticio")
        periodo.refresh_from_db()
        self.assertEqual(periodo.estado, Periodo.Estado.CERRADO)
        reabrir_periodo(periodo, actor=self.administrador, motivo="Reapertura ficticia")
        periodo.refresh_from_db()
        self.assertEqual(periodo.estado, Periodo.Estado.ABIERTO)
        self.assertTrue(RegistroBitacora.objects.filter(accion="periodo.cerrado").exists())
        self.assertTrue(RegistroBitacora.objects.filter(accion="periodo.abierto").count() >= 2)

    def test_periodo_cerrado_bloquea_edicion_ordinaria_del_coordinador(self):
        periodo = self.abrir()
        proyeccion = ProyeccionArea.objects.get(periodo=periodo, area=self.area_activa)
        linea = Linea.objects.create(
            proyeccion=proyeccion,
            producto_servicio="Guantes de examen",
            unidad=self.unidad,
            precio_estimado=Decimal("12.50"),
        )
        cerrar_periodo(periodo, actor=self.administrador, motivo="Cierre ficticio")
        linea.cantidad_enero = 1
        with self.assertRaises(ValidationError) as contexto:
            guardar_linea(linea, actor=self.coordinador, motivo="Edición ficticia")
        self.assertIn("proyeccion", contexto.exception.message_dict)


class PeriodosVistasTests(TestCase):
    def setUp(self):
        self.area = crear_area()
        self.area_inactiva = crear_area("Laboratorio", "LAB")
        Area.objects.filter(pk=self.area_inactiva.pk).update(activa=False)
        self.administrador = crear_usuario(Rol.ADMINISTRADOR, correo="admin-vistas@ejemplo.test")
        self.desarrollador = crear_usuario(Rol.DESARROLLADOR, correo="dev-vistas@ejemplo.test")
        self.coordinador = crear_usuario(Rol.COORDINADOR, correo="coord-vistas@ejemplo.test", area=self.area)
        self.proveedor = crear_usuario(Rol.PROVEEDOR, correo="prov-vistas@ejemplo.test")
        self.url = reverse("proyecciones:abrir_periodo")

    def test_administrador_abre_periodo_desde_la_vista(self):
        self.client.force_login(self.administrador)
        respuesta = self.client.post(
            self.url,
            {"anio": 2027, "fecha_limite": "2027-12-15", "motivo": MOTIVO},
        )
        self.assertRedirects(respuesta, self.url)
        periodo = Periodo.objects.get(anio=2027)
        self.assertEqual(ProyeccionArea.objects.filter(periodo=periodo).count(), 1)

    def test_ano_duplicado_muestra_error_en_la_vista(self):
        self.client.force_login(self.administrador)
        self.client.post(self.url, {"anio": 2027, "fecha_limite": "2027-12-15", "motivo": MOTIVO})
        respuesta = self.client.post(
            self.url,
            {"anio": 2027, "fecha_limite": "2027-12-15", "motivo": MOTIVO},
        )
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, "Ya existe un periodo")

    def test_solo_administradores_pueden_abrir_periodos(self):
        for usuario in (self.coordinador, self.proveedor):
            with self.subTest(usuario=usuario.rol):
                self.client.force_login(usuario)
                self.assertEqual(self.client.get(self.url).status_code, 403)
        for usuario in (self.administrador, self.desarrollador):
            with self.subTest(usuario=usuario.rol):
                self.client.force_login(usuario)
                self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_coordinador_ve_periodo_abierto_y_luego_ve_bloqueo_cerrado(self):
        self.client.force_login(self.administrador)
        self.client.post(self.url, {"anio": 2027, "fecha_limite": "2027-12-15", "motivo": MOTIVO})
        periodo = Periodo.objects.get(anio=2027)

        self.client.force_login(self.coordinador)
        respuesta = self.client.get(reverse("proyecciones:mi_proyeccion"))
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, "Puede diligenciar su proyección.")

        cerrar_periodo(periodo, actor=self.administrador, motivo="Cierre de prueba")
        respuesta = self.client.get(reverse("proyecciones:mi_proyeccion"))
        self.assertContains(respuesta, "edición ordinaria bloqueada")

    def test_solo_coordinadores_pueden_ver_mi_proyeccion(self):
        for usuario in (self.administrador, self.desarrollador, self.proveedor):
            with self.subTest(usuario=usuario.rol):
                self.client.force_login(usuario)
                self.assertEqual(self.client.get(reverse("proyecciones:mi_proyeccion")).status_code, 403)
        self.client.force_login(self.coordinador)
        self.assertEqual(self.client.get(reverse("proyecciones:mi_proyeccion")).status_code, 200)

    def test_coordinador_y_proveedor_no_pueden_cerrar_periodo(self):
        self.client.force_login(self.administrador)
        self.client.post(self.url, {"anio": 2027, "fecha_limite": "2027-12-15", "motivo": MOTIVO})
        periodo = Periodo.objects.get(anio=2027)
        url = reverse("proyecciones:periodo_estado", args=[periodo.pk])
        for usuario in (self.coordinador, self.proveedor):
            with self.subTest(usuario=usuario.rol):
                self.client.force_login(usuario)
                self.assertEqual(self.client.post(url, {"motivo": "Intento"}).status_code, 403)

    def test_activar_area_ofrece_crear_proyeccion(self):
        self.client.force_login(self.administrador)
        self.client.post(self.url, {"anio": 2027, "fecha_limite": "2027-12-15", "motivo": MOTIVO})
        Area.objects.filter(pk=self.area_inactiva.pk).update(activa=False)
        respuesta = self.client.post(
            reverse("configuracion:area_estado", args=[self.area_inactiva.pk]),
            {"motivo": "Reactivación ficticia"},
            follow=True,
        )
        self.assertContains(respuesta, "Crear la proyección")
        periodo = Periodo.objects.get(anio=2027)
        self.assertFalse(ProyeccionArea.objects.filter(periodo=periodo, area=self.area_inactiva).exists())
        self.client.post(
            reverse(
                "proyecciones:crear_proyeccion_area",
                args=[periodo.pk, self.area_inactiva.pk],
            ),
            {"motivo": "Completar proyección ficticia"},
        )
        self.assertTrue(ProyeccionArea.objects.filter(periodo=periodo, area=self.area_inactiva).exists())

    def test_crear_area_nueva_con_periodo_abierto_ofrece_proyeccion(self):
        self.client.force_login(self.administrador)
        self.client.post(self.url, {"anio": 2027, "fecha_limite": "2027-12-15", "motivo": MOTIVO})
        respuesta = self.client.post(
            reverse("configuracion:area_nueva"),
            {"nombre": "Urgencias", "codigo_area": "URG", "motivo": "Alta ficticia"},
            follow=True,
        )
        self.assertContains(respuesta, "Crear la proyección")
        periodo = Periodo.objects.get(anio=2027)
        area = Area.objects.get(codigo_area="URG")
        self.assertFalse(ProyeccionArea.objects.filter(periodo=periodo, area=area).exists())


class LineasVistasTests(TestCase):
    def setUp(self):
        self.area = crear_area("Farmacia", "FAR")
        self.otra_area = crear_area("Laboratorio", "LAB")
        self.administrador = crear_usuario(Rol.ADMINISTRADOR, correo="admin-lineas@ejemplo.test")
        self.coordinador = crear_usuario(Rol.COORDINADOR, correo="coord-lineas@ejemplo.test", area=self.area)
        self.otro_coordinador = crear_usuario(
            Rol.COORDINADOR,
            correo="coord-otra-lineas@ejemplo.test",
            area=self.otra_area,
        )
        self.unidad = UnidadMedida.objects.create(nombre="Caja", abreviatura="cja")
        self.periodo = Periodo.objects.create(
            anio=2028,
            fecha_apertura=date(2028, 1, 1),
            fecha_limite_diligenciamiento=date(2028, 12, 15),
            creado_por=self.administrador,
        )
        self.proyeccion = ProyeccionArea.objects.create(periodo=self.periodo, area=self.area)
        self.otra_proyeccion = ProyeccionArea.objects.create(periodo=self.periodo, area=self.otra_area)
        self.url = reverse("proyecciones:mi_proyeccion_detalle", args=[self.proyeccion.pk])

    def datos_linea(self, accion="guardar", iniciales=0, **cambios):
        datos = {
            "lineas-TOTAL_FORMS": "1",
            "lineas-INITIAL_FORMS": str(iniciales),
            "lineas-MIN_NUM_FORMS": "0",
            "lineas-MAX_NUM_FORMS": "1000",
            "lineas-0-id": "",
            "lineas-0-producto_servicio": "Guantes de examen",
            "lineas-0-dependencia": "Urgencias",
            "lineas-0-unidad": str(self.unidad.pk),
            "lineas-0-precio_estimado": "12.50",
            "motivo": "Actualización ficticia de la proyección",
            "accion": accion,
        }
        for campo in CAMPOS_CANTIDADES_MENSUALES:
            datos[f"lineas-0-{campo}"] = "0"
        datos.update(cambios)
        return datos

    def datos_sin_lineas(self):
        return {
            "lineas-TOTAL_FORMS": "0",
            "lineas-INITIAL_FORMS": "0",
            "lineas-MIN_NUM_FORMS": "0",
            "lineas-MAX_NUM_FORMS": "1000",
            "motivo": "Envío ficticio sin líneas",
            "accion": "enviar",
        }

    def test_guardar_borrador_crea_linea_y_calcula_valores_oficiales(self):
        self.client.force_login(self.coordinador)
        respuesta = self.client.post(
            self.url,
            self.datos_linea(**{"lineas-0-cantidad_enero": "2", "lineas-0-cantidad_febrero": "3"}),
        )
        self.assertRedirects(respuesta, self.url)
        linea = Linea.objects.get(proyeccion=self.proyeccion)
        self.assertEqual(linea.total_anual, 5)
        self.assertEqual(linea.costo_anual, Decimal("62.50"))
        self.assertEqual(linea.proyeccion.estado, ProyeccionArea.Estado.BORRADOR)
        self.assertTrue(RegistroBitacora.objects.filter(accion="linea.creada", objeto_id=str(linea.pk)).exists())

    def test_editar_y_quitar_linea_deja_bitacora(self):
        linea = Linea.objects.create(
            proyeccion=self.proyeccion,
            producto_servicio="Guantes de examen",
            dependencia="Urgencias",
            unidad=self.unidad,
            cantidad_enero=1,
            precio_estimado=Decimal("12.50"),
        )
        self.client.force_login(self.coordinador)
        datos = self.datos_linea(iniciales=1, **{"lineas-0-id": str(linea.pk), "lineas-0-cantidad_enero": "4"})
        self.client.post(self.url, datos)
        linea.refresh_from_db()
        self.assertEqual(linea.cantidad_enero, 4)
        self.assertTrue(RegistroBitacora.objects.filter(accion="linea.modificada", objeto_id=str(linea.pk)).exists())

        datos = self.datos_linea(
            iniciales=1,
            **{"lineas-0-id": str(linea.pk), "lineas-0-DELETE": "on"},
        )
        self.client.post(self.url, datos)
        self.assertFalse(Linea.objects.filter(pk=linea.pk).exists())
        self.assertTrue(RegistroBitacora.objects.filter(accion="linea.eliminada", objeto_id=str(linea.pk)).exists())

    def test_cantidades_negativas_y_decimales_se_rechazan(self):
        self.client.force_login(self.coordinador)
        casos = [
            {"lineas-0-cantidad_enero": "-1"},
            {"lineas-0-cantidad_enero": "1.5"},
            {"lineas-0-precio_estimado": "12.345"},
        ]
        for cambios in casos:
            with self.subTest(cambios=cambios):
                respuesta = self.client.post(self.url, self.datos_linea(**cambios))
                self.assertEqual(respuesta.status_code, 200)
                self.assertTrue(respuesta.context["formset"].errors)
                self.assertFalse(Linea.objects.filter(proyeccion=self.proyeccion).exists())

    def test_unidad_es_obligatoria_y_debe_estar_activa(self):
        inactiva = UnidadMedida.objects.create(nombre="Frasco", abreviatura="fco", activa=False)
        self.client.force_login(self.coordinador)
        for valor in ("", str(inactiva.pk)):
            with self.subTest(valor=valor):
                respuesta = self.client.post(self.url, self.datos_linea(**{"lineas-0-unidad": valor}))
                self.assertEqual(respuesta.status_code, 200)
                self.assertTrue(respuesta.context["formset"].errors)
                self.assertFalse(Linea.objects.filter(proyeccion=self.proyeccion).exists())

    def test_enviar_exige_al_menos_una_linea(self):
        self.client.force_login(self.coordinador)
        respuesta = self.client.post(self.url, self.datos_sin_lineas())
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, "debe existir al menos una línea")
        self.proyeccion.refresh_from_db()
        self.assertEqual(self.proyeccion.estado, ProyeccionArea.Estado.BORRADOR)

    def test_enviar_fecha_usuario_y_deja_la_proyeccion_en_solo_lectura(self):
        self.client.force_login(self.coordinador)
        respuesta = self.client.post(self.url, self.datos_linea(accion="enviar"))
        self.assertRedirects(respuesta, self.url)
        self.proyeccion.refresh_from_db()
        self.assertEqual(self.proyeccion.estado, ProyeccionArea.Estado.ENVIADA)
        self.assertEqual(self.proyeccion.enviado_por, self.coordinador)
        self.assertIsNotNone(self.proyeccion.fecha_envio)
        self.assertTrue(
            RegistroBitacora.objects.filter(
                accion="proyeccion_area.enviada", objeto_id=str(self.proyeccion.pk)
            ).exists()
        )
        self.assertContains(self.client.get(self.url), "solo lectura")

        linea = Linea.objects.get(proyeccion=self.proyeccion)
        datos = self.datos_linea(
            iniciales=1,
            **{"lineas-0-id": str(linea.pk), "lineas-0-cantidad_enero": "9"},
        )
        respuesta = self.client.post(self.url, datos)
        self.assertEqual(respuesta.status_code, 200)
        linea.refresh_from_db()
        self.assertEqual(linea.cantidad_enero, 0)

    def test_periodo_cerrado_bloquea_guardar_desde_la_vista(self):
        linea = Linea.objects.create(
            proyeccion=self.proyeccion,
            producto_servicio="Guantes de examen",
            unidad=self.unidad,
            precio_estimado=Decimal("12.50"),
        )
        cerrar_periodo(self.periodo, actor=self.administrador, motivo="Cierre ficticio")
        self.client.force_login(self.coordinador)
        self.assertContains(self.client.get(self.url), "edición ordinaria bloqueada")
        respuesta = self.client.post(
            self.url,
            self.datos_linea(
                iniciales=1,
                **{"lineas-0-id": str(linea.pk), "lineas-0-cantidad_enero": "7"},
            ),
        )
        self.assertEqual(respuesta.status_code, 200)
        linea.refresh_from_db()
        self.assertEqual(linea.cantidad_enero, 0)

    def test_no_puede_ver_ni_editar_proyeccion_de_otra_area_por_id(self):
        Linea.objects.create(
            proyeccion=self.otra_proyeccion,
            producto_servicio="Dato privado ficticio",
            unidad=self.unidad,
            precio_estimado=Decimal("5.00"),
        )
        self.client.force_login(self.coordinador)
        url_ajena = reverse("proyecciones:mi_proyeccion_detalle", args=[self.otra_proyeccion.pk])
        self.assertEqual(self.client.get(url_ajena).status_code, 404)
        self.assertEqual(self.client.post(url_ajena, self.datos_linea()).status_code, 404)

    def test_id_de_linea_ajena_en_el_formset_se_rechaza(self):
        ajena = Linea.objects.create(
            proyeccion=self.otra_proyeccion,
            producto_servicio="Dato privado ficticio",
            unidad=self.unidad,
            cantidad_enero=3,
            precio_estimado=Decimal("5.00"),
        )
        self.client.force_login(self.coordinador)
        casos = {
            "editar": {"lineas-0-id": str(ajena.pk), "lineas-0-cantidad_enero": "99"},
            "quitar": {"lineas-0-id": str(ajena.pk), "lineas-0-DELETE": "on"},
        }
        for nombre, cambios in casos.items():
            for accion in ("guardar", "enviar"):
                with self.subTest(caso=nombre, accion=accion):
                    respuesta = self.client.post(self.url, self.datos_linea(accion=accion, iniciales=1, **cambios))
                    self.assertEqual(respuesta.status_code, 200)
                    self.assertContains(respuesta, "no pertenece a esta proyección")
                    ajena.refresh_from_db()
                    self.assertEqual(ajena.cantidad_enero, 3)
                    self.assertEqual(ajena.proyeccion, self.otra_proyeccion)
                    self.assertFalse(Linea.objects.filter(proyeccion=self.proyeccion).exists())
                    self.proyeccion.refresh_from_db()
                    self.assertEqual(self.proyeccion.estado, ProyeccionArea.Estado.BORRADOR)
        self.assertFalse(RegistroBitacora.objects.filter(objeto_id=str(ajena.pk)).exists())

    def test_id_de_linea_propia_en_fila_nueva_no_la_duplica(self):
        propia = Linea.objects.create(
            proyeccion=self.proyeccion,
            producto_servicio="Guantes de examen",
            unidad=self.unidad,
            precio_estimado=Decimal("12.50"),
        )
        self.client.force_login(self.coordinador)
        respuesta = self.client.post(self.url, self.datos_linea(**{"lineas-0-id": str(propia.pk)}))
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, "no pertenece a esta proyección")
        self.assertEqual(Linea.objects.filter(proyeccion=self.proyeccion).count(), 1)

    def test_conserva_unidad_que_se_desactivo_despues(self):
        linea = Linea.objects.create(
            proyeccion=self.proyeccion,
            producto_servicio="Guantes de examen",
            unidad=self.unidad,
            precio_estimado=Decimal("12.50"),
        )
        UnidadMedida.objects.filter(pk=self.unidad.pk).update(activa=False)
        self.client.force_login(self.coordinador)
        respuesta = self.client.post(
            self.url,
            self.datos_linea(iniciales=1, **{"lineas-0-id": str(linea.pk), "lineas-0-cantidad_marzo": "6"}),
        )
        self.assertRedirects(respuesta, self.url)
        linea.refresh_from_db()
        self.assertEqual(linea.cantidad_marzo, 6)
        self.assertEqual(linea.unidad, self.unidad)

    def test_casillas_de_la_tabla_tienen_nombre_accesible(self):
        self.client.force_login(self.coordinador)
        respuesta = self.client.get(self.url)
        self.assertContains(respuesta, 'aria-label="Cantidad de enero, línea 1"')
        self.assertContains(respuesta, 'aria-label="Precio unitario estimado de referencia, línea nueva"')
        self.assertContains(respuesta, 'aria-label="Costo proyectado total informado, línea nueva"')


class LineaServicioTests(TestCase):
    """La regla de unidad activa vive en el servicio, no solo en el formulario."""

    def setUp(self):
        self.area = crear_area("Farmacia", "FAR")
        self.administrador = crear_usuario(Rol.ADMINISTRADOR, correo="admin-servicio-linea@ejemplo.test")
        self.coordinador = crear_usuario(
            Rol.COORDINADOR, correo="coord-servicio-linea@ejemplo.test", area=self.area
        )
        self.activa = UnidadMedida.objects.create(nombre="Caja", abreviatura="cja")
        self.inactiva = UnidadMedida.objects.create(nombre="Frasco", abreviatura="fco", activa=False)
        periodo = Periodo.objects.create(
            anio=2029,
            fecha_apertura=date(2029, 1, 1),
            fecha_limite_diligenciamiento=date(2029, 12, 15),
            creado_por=self.administrador,
        )
        self.proyeccion = ProyeccionArea.objects.create(periodo=periodo, area=self.area)

    def nueva_linea(self, unidad):
        return Linea(
            proyeccion=self.proyeccion,
            producto_servicio="Jeringas ficticias",
            unidad=unidad,
            precio_estimado=Decimal("1.00"),
        )

    def test_rechaza_unidad_inactiva_en_linea_nueva(self):
        with self.assertRaises(ValidationError) as contexto:
            guardar_linea(self.nueva_linea(self.inactiva), actor=self.coordinador, motivo=MOTIVO)
        self.assertIn("unidad", contexto.exception.message_dict)
        self.assertFalse(Linea.objects.exists())

    def test_rechaza_cambiar_a_unidad_inactiva(self):
        linea = self.nueva_linea(self.activa)
        guardar_linea(linea, actor=self.coordinador, motivo=MOTIVO)
        linea.unidad = self.inactiva
        with self.assertRaises(ValidationError):
            guardar_linea(linea, actor=self.coordinador, motivo=MOTIVO)
        linea.refresh_from_db()
        self.assertEqual(linea.unidad, self.activa)

    def test_conserva_unidad_desactivada_despues(self):
        linea = self.nueva_linea(self.activa)
        guardar_linea(linea, actor=self.coordinador, motivo=MOTIVO)
        UnidadMedida.objects.filter(pk=self.activa.pk).update(activa=False)
        linea.cantidad_abril = 8
        guardar_linea(linea, actor=self.coordinador, motivo=MOTIVO)
        linea.refresh_from_db()
        self.assertEqual(linea.cantidad_abril, 8)


class MiProyeccionPermisosTests(TestCase):
    """Matriz de roles para las dos URL de «Mi proyección» (GET y POST)."""

    def setUp(self):
        self.area = crear_area("Farmacia", "FAR")
        self.administrador = crear_usuario(Rol.ADMINISTRADOR, correo="admin-matriz@ejemplo.test")
        self.desarrollador = crear_usuario(Rol.DESARROLLADOR, correo="dev-matriz@ejemplo.test")
        self.proveedor = crear_usuario(Rol.PROVEEDOR, correo="prov-matriz@ejemplo.test")
        self.coordinador = crear_usuario(Rol.COORDINADOR, correo="coord-matriz@ejemplo.test", area=self.area)
        self.unidad = UnidadMedida.objects.create(nombre="Caja", abreviatura="cja")
        periodo = Periodo.objects.create(
            anio=2030,
            fecha_apertura=date(2030, 1, 1),
            fecha_limite_diligenciamiento=date(2030, 12, 15),
            creado_por=self.administrador,
        )
        self.proyeccion = ProyeccionArea.objects.create(periodo=periodo, area=self.area)
        self.urls = [
            reverse("proyecciones:mi_proyeccion"),
            reverse("proyecciones:mi_proyeccion_detalle", args=[self.proyeccion.pk]),
        ]
        self.datos = {
            "lineas-TOTAL_FORMS": "1",
            "lineas-INITIAL_FORMS": "0",
            "lineas-MIN_NUM_FORMS": "0",
            "lineas-MAX_NUM_FORMS": "1000",
            "lineas-0-id": "",
            "lineas-0-producto_servicio": "Guantes de examen",
            "lineas-0-unidad": str(self.unidad.pk),
            "lineas-0-precio_estimado": "1.00",
            "motivo": "Intento ficticio",
            "accion": "enviar",
        }
        for campo in CAMPOS_CANTIDADES_MENSUALES:
            self.datos[f"lineas-0-{campo}"] = "1"

    def assert_sin_cambios(self):
        self.assertFalse(Linea.objects.exists())
        self.proyeccion.refresh_from_db()
        self.assertEqual(self.proyeccion.estado, ProyeccionArea.Estado.BORRADOR)

    def test_roles_no_coordinadores_reciben_403_en_get_y_post(self):
        for usuario in (self.administrador, self.desarrollador, self.proveedor):
            self.client.force_login(usuario)
            for url in self.urls:
                with self.subTest(rol=usuario.rol, url=url):
                    self.assertEqual(self.client.get(url).status_code, 403)
                    self.assertEqual(self.client.post(url, self.datos).status_code, 403)
                    self.assert_sin_cambios()

    def test_sin_sesion_redirige_al_ingreso(self):
        ingreso = reverse("cuentas:ingresar")
        for url in self.urls:
            with self.subTest(url=url):
                for respuesta in (self.client.get(url), self.client.post(url, self.datos)):
                    self.assertEqual(respuesta.status_code, 302)
                    self.assertTrue(respuesta["Location"].startswith(ingreso))
                self.assert_sin_cambios()

    def test_coordinador_del_area_accede_a_ambas_urls(self):
        self.client.force_login(self.coordinador)
        for url in self.urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)
