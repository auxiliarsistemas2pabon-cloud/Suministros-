"""El panel y la navegación respetan el alcance y los accesos de cada rol."""

from datetime import date

from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory, TestCase
from django.urls import resolve, reverse
from django.utils import timezone

from cuentas.consultas import resumen_inicio
from cuentas.models import Rol
from cuentas.navegacion import menu_para
from cuentas.tests.utilidades import crear_area, crear_usuario
from proveedores.tests.utilidades import crear_proveedor
from proyecciones.models import Periodo, ProyeccionArea


class PresentacionTests(TestCase):
    def menu(self, usuario, ruta):
        solicitud = RequestFactory().get(ruta)
        solicitud.user = usuario
        solicitud.resolver_match = resolve(ruta)
        return menu_para(usuario, solicitud)

    def enlaces(self, menu):
        return [enlace for grupo in menu["grupos_menu"] for enlace in grupo["enlaces"]]

    def test_anonimo_e_inactivo_no_reciben_datos_ni_consultan_la_base(self):
        inactivo = crear_usuario(Rol.ADMINISTRADOR, activo=False)
        for usuario in (AnonymousUser(), inactivo):
            with self.subTest(usuario=usuario), self.assertNumQueries(0):
                self.assertEqual(resumen_inicio(usuario)["indicadores"], [])
                self.assertEqual(self.menu(usuario, "/")["grupos_menu"], [])

    def test_rutas_anidadas_destacan_solo_el_modulo_correspondiente(self):
        admin = crear_usuario(Rol.ADMINISTRADOR)
        casos = [
            ("/compras/ordenes/123/", "compras:ordenes"),
            ("/compras/cotizaciones/123/comparar/", "compras:cotizaciones"),
            ("/proyecciones/periodos/123/estado/", "proyecciones:abrir_periodo"),
            ("/configuracion/usuarios/", "configuracion:inicio"),
        ]
        for ruta, seccion in casos:
            with self.subTest(ruta=ruta), self.assertNumQueries(0):
                menu = self.menu(admin, ruta)
                activos = [enlace for enlace in self.enlaces(menu) if enlace["activo"]]
                self.assertEqual(menu["seccion_menu"], seccion)
                self.assertEqual(len(activos), 1)
                self.assertEqual(activos[0]["url"], reverse(seccion))

    def test_coordinador_y_proveedor_no_reciben_enlaces_administrativos(self):
        for rol, esperado in (
            (Rol.COORDINADOR, "proyecciones:mi_proyeccion"),
            (Rol.PROVEEDOR, "portal:inicio"),
        ):
            usuario = crear_usuario(rol)
            with self.subTest(rol=rol):
                enlaces = self.enlaces(self.menu(usuario, reverse(esperado)))
                self.assertEqual([enlace["url"] for enlace in enlaces], [reverse(esperado)])
                self.assertTrue(enlaces[0]["activo"])
                self.client.force_login(usuario)
                self.assertEqual(self.client.get(reverse("compras:ordenes")).status_code, 403)

    def test_indicadores_del_coordinador_no_incluyen_otras_areas(self):
        admin = crear_usuario(Rol.ADMINISTRADOR)
        coordinador = crear_usuario(Rol.COORDINADOR)
        otra_area = crear_area("Laboratorio", "LAB")
        for anio, estado in ((2025, "aprobada"), (2026, "enviada"), (2027, "borrador")):
            periodo = Periodo.objects.create(
                anio=anio,
                fecha_apertura=date(anio, 1, 1),
                fecha_limite_diligenciamiento=date(anio, 12, 31),
                creado_por=admin,
            )
            datos_envio = {}
            if estado in ("enviada", "aprobada"):
                datos_envio.update(fecha_envio=timezone.now(), enviado_por=coordinador)
            if estado == "aprobada":
                datos_envio.update(fecha_aprobacion=timezone.now(), aprobado_por=admin)
            ProyeccionArea.objects.create(periodo=periodo, area=coordinador.area, estado=estado, **datos_envio)
            ProyeccionArea.objects.create(periodo=periodo, area=otra_area, estado=estado, **datos_envio)
        with self.assertNumQueries(1):
            resumen = resumen_inicio(coordinador)
        self.assertEqual([dato["valor"] for dato in resumen["indicadores"]], [3, 1, 1, 1])
        self.assertEqual(resumen["ordenes_recientes"], [])
        self.assertFalse(resumen["configuracion_pendiente"])
        self.client.force_login(coordinador)
        self.assertNotContains(self.client.get("/"), "Proveedores registrados")

    def test_administracion_muestra_el_conteo_real_y_la_configuracion_pendiente(self):
        admin = crear_usuario(Rol.ADMINISTRADOR)
        crear_proveedor()
        crear_proveedor()
        self.client.force_login(admin)
        respuesta = self.client.get("/")
        self.assertEqual([dato["valor"] for dato in respuesta.context["indicadores"]], [2, 0, 0, 0])
        self.assertTrue(respuesta.context["configuracion_pendiente"])
        self.assertContains(respuesta, "Complete los datos de la clínica")
        self.assertContains(respuesta, reverse("configuracion:parametros"))

    def test_proveedor_no_recibe_indicadores_globales(self):
        proveedor = crear_usuario(Rol.PROVEEDOR)
        with self.assertNumQueries(0):
            resumen = resumen_inicio(proveedor)
        self.assertEqual(resumen["indicadores"], [])
        self.assertEqual(resumen["ordenes_recientes"], [])
        self.assertFalse(resumen["configuracion_pendiente"])
