"""Rutas y formularios de catálogos FR14, con permisos en GET y POST."""

from django.test import TestCase
from django.urls import resolve, reverse

from bitacora.models import RegistroBitacora
from cuentas.models import ROLES_ADMIN, Rol
from cuentas.tests.utilidades import crear_usuario
from proveedores.catalogos import CATALOGOS
from proveedores.models import CategoriaProveedor, Peso, Requisito, TipoDocumento

MOTIVO = "Configuración de ejemplo ficticio"


class PanelProveedoresTests(TestCase):
    def setUp(self):
        self.admin = crear_usuario(Rol.ADMINISTRADOR)
        self.dev = crear_usuario(Rol.DESARROLLADOR)
        self.coordinador = crear_usuario(Rol.COORDINADOR)
        self.proveedor = crear_usuario(Rol.PROVEEDOR)
        self.categoria = CategoriaProveedor.objects.create(nombre="Categoría de ejemplo")
        self.tipo = TipoDocumento.objects.create(nombre="Documento de ejemplo")
        self.requisito = Requisito.objects.create(numero=1, grupo="calidad", texto="Texto de ejemplo")
        self.peso = Peso.objects.create(requisito=self.requisito, categoria=self.categoria, valor=1)
        self.objetos = {"categorias": self.categoria, "tipos-documento": self.tipo, "requisitos": self.requisito, "pesos": self.peso}

    def url(self, nombre, catalogo, pk=None):
        kwargs = {"catalogo": catalogo}
        if pk:
            kwargs["pk"] = pk
        return reverse("configuracion:" + nombre, kwargs=kwargs)

    def rutas(self):
        for catalogo, objeto in self.objetos.items():
            yield self.url("catalogos_proveedores", catalogo)
            yield self.url("catalogo_proveedor_nuevo", catalogo)
            yield self.url("catalogo_proveedor_editar", catalogo, objeto.pk)
            if catalogo != "pesos":
                yield self.url("catalogo_proveedor_estado", catalogo, objeto.pk)

    def test_coordinador_y_proveedor_403_en_todas_las_rutas(self):
        for usuario in (self.coordinador, self.proveedor):
            self.client.force_login(usuario)
            for ruta in self.rutas():
                with self.subTest(rol=usuario.rol, ruta=ruta):
                    self.assertEqual(self.client.get(ruta).status_code, 403)
                    self.assertEqual(self.client.post(ruta, {"motivo": MOTIVO}).status_code, 403)
                    self.assertEqual(resolve(ruta).func.roles_permitidos, frozenset(ROLES_ADMIN))
        self.assertFalse(RegistroBitacora.objects.exists())

    def test_anonimo_redirigido_y_administracion_admitida(self):
        for ruta in self.rutas():
            self.assertEqual(self.client.get(ruta).status_code, 302)
        for usuario in (self.admin, self.dev):
            self.client.force_login(usuario)
            for ruta in self.rutas():
                with self.subTest(rol=usuario.rol, ruta=ruta):
                    self.assertEqual(self.client.get(ruta).status_code, 200)

    def test_crear_y_editar_cada_catalogo_con_bitacora(self):
        self.client.force_login(self.admin)
        casos = {
            "categorias": ({"nombre": "Nueva categoría", "descripcion": "Descripción ficticia"}, {"nombre": "Categoría editada", "descripcion": "Nueva descripción"}),
            "tipos-documento": ({"nombre": "Nuevo tipo", "dias_alerta": 45, "requiere_vencimiento": True}, {"nombre": "Tipo editado", "dias_alerta": 60, "requiere_vencimiento": True}),
            "requisitos": ({"numero": 2, "grupo": "sgsst", "texto": "Texto ficticio"}, {"numero": 3, "grupo": "ambiental", "texto": "Texto editado"}),
        }
        for catalogo, (nuevo, cambio) in casos.items():
            with self.subTest(catalogo=catalogo):
                respuesta = self.client.post(self.url("catalogo_proveedor_nuevo", catalogo), {**nuevo, "motivo": MOTIVO})
                self.assertEqual(respuesta.status_code, 302)
                objeto = CATALOGOS[catalogo]["modelo"].objects.order_by("-pk").first()
                respuesta = self.client.post(self.url("catalogo_proveedor_editar", catalogo, objeto.pk), {**cambio, "motivo": MOTIVO})
                self.assertEqual(respuesta.status_code, 302)
                self.assertTrue(RegistroBitacora.objects.filter(accion=CATALOGOS[catalogo]["accion"] + ".modificado").exists())
        otro = Requisito.objects.create(numero=4, grupo="calidad", texto="Otro requisito")
        datos = {"requisito": otro.pk, "categoria": self.categoria.pk, "valor": 2, "motivo": MOTIVO}
        self.assertEqual(self.client.post(self.url("catalogo_proveedor_nuevo", "pesos"), datos).status_code, 302)
        peso = Peso.objects.get(requisito=otro)
        self.assertEqual(self.client.post(self.url("catalogo_proveedor_editar", "pesos", peso.pk), {**datos, "valor": 1}).status_code, 302)
        peso.refresh_from_db()
        self.assertEqual(peso.valor, 1)

    def test_desactivar_y_reactivar_no_borra_relaciones(self):
        self.client.force_login(self.admin)
        for catalogo in ("categorias", "tipos-documento", "requisitos"):
            objeto = self.objetos[catalogo]
            ruta = self.url("catalogo_proveedor_estado", catalogo, objeto.pk)
            self.assertEqual(self.client.post(ruta, {"motivo": ""}).status_code, 200)
            objeto.refresh_from_db()
            self.assertTrue(objeto.activo)
            self.assertEqual(self.client.post(ruta, {"motivo": MOTIVO}).status_code, 302)
            objeto.refresh_from_db()
            self.assertFalse(objeto.activo)
            self.client.post(ruta, {"motivo": MOTIVO})
            objeto.refresh_from_db()
            self.assertTrue(objeto.activo)
        self.assertTrue(Peso.objects.filter(pk=self.peso.pk).exists())

    def test_peso_invalido_sin_motivo_y_duplicado_no_guardan(self):
        self.client.force_login(self.admin)
        ruta = self.url("catalogo_proveedor_nuevo", "pesos")
        for valor, motivo in ((3, MOTIVO), (2, ""), (2, MOTIVO)):
            respuesta = self.client.post(ruta, {"requisito": self.requisito.pk, "categoria": self.categoria.pk, "valor": valor, "motivo": motivo})
            self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(Peso.objects.count(), 1)

    def test_filtros_combinables_y_errores_visibles(self):
        self.client.force_login(self.admin)
        ruta = self.url("catalogos_proveedores", "pesos")
        self.assertEqual(self.client.get(ruta, {"grupo": "ambiental"}).context["pagina"].paginator.count, 0)
        self.assertEqual(self.client.get(ruta, {"grupo": "calidad", "categoria": self.categoria.pk, "q": "ejemplo"}).context["pagina"].paginator.count, 1)
        respuesta = self.client.get(ruta, {"categoria": 999999})
        self.assertTrue(respuesta.context["filtro"].errors)
        self.assertEqual(respuesta.context["pagina"].paginator.count, 0)
        self.assertContains(respuesta, "errorlist")

    def test_catalogos_desconocidos_y_borrado_no_existen(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(self.url("catalogos_proveedores", "desconocido")).status_code, 404)
        for catalogo, objeto in self.objetos.items():
            self.assertEqual(self.client.post(f"/configuracion/proveedores/{catalogo}/{objeto.pk}/borrar/").status_code, 404)

    def test_menu_y_panel_enlazan_catalogos(self):
        self.client.force_login(self.admin)
        respuesta = self.client.get(reverse("configuracion:inicio"))
        self.assertContains(respuesta, self.url("catalogos_proveedores", "categorias"))
