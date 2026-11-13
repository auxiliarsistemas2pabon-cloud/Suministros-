"""Permisos de /proveedores/: solo administrador y desarrollador.

Coordinadores y proveedores reciben 403 en todas las vistas (GET y POST) sin cambiar
datos; tampoco pueden descargar documentos, ni siquiera los de su propia ficha.
"""

from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from bitacora.models import RegistroBitacora
from cuentas.models import Rol
from cuentas.tests.utilidades import crear_area, crear_usuario
from proveedores import servicios
from proveedores.models import DocumentoProveedor, Proveedor
from proveedores.tests.utilidades import MOTIVO, MediaTemporal, crear_proveedor, pdf, tipo_documento


class PermisosProveedoresTests(MediaTemporal, TestCase):
    def setUp(self):
        super().setUp()
        self.area = crear_area()
        self.administrador = crear_usuario(Rol.ADMINISTRADOR, correo="admin@ejemplo.test")
        self.desarrollador = crear_usuario(Rol.DESARROLLADOR, correo="dev@ejemplo.test")
        self.coordinador = crear_usuario(Rol.COORDINADOR, correo="coord@ejemplo.test", area=self.area)
        self.proveedor_ficha = crear_proveedor(razon_social="Proveedor Propio Ficticio")
        self.usuario_proveedor = crear_usuario(Rol.PROVEEDOR, correo="prov@ejemplo.test", proveedor=self.proveedor_ficha)
        hoy = timezone.localdate()
        with self.captureOnCommitCallbacks(execute=True):
            self.documento = servicios.guardar_documento(
                DocumentoProveedor(
                    proveedor=self.proveedor_ficha,
                    tipo=tipo_documento(),
                    fecha_expedicion=hoy - timedelta(days=1),
                    fecha_vencimiento=hoy + timedelta(days=90),
                ),
                actor=self.administrador,
                motivo=MOTIVO,
                archivo_subido=pdf(),
            )

    def urls(self):
        p, d = self.proveedor_ficha.pk, self.documento.pk
        return [
            reverse("proveedores:lista"),
            reverse("proveedores:nuevo"),
            reverse("proveedores:vencimientos"),
            reverse("proveedores:detalle", args=[p]),
            reverse("proveedores:editar", args=[p]),
            reverse("proveedores:estado", args=[p]),
            reverse("proveedores:documento_nuevo", args=[p]),
            reverse("proveedores:documento_editar", args=[p, d]),
            reverse("proveedores:documento_eliminar", args=[p, d]),
            reverse("proveedores:documento_descargar", args=[p, d]),
        ]

    def test_todas_las_vistas_usan_rol_requerido(self):
        from django.urls import resolve

        for url in self.urls():
            with self.subTest(url=url):
                vista = resolve(url).func
                self.assertEqual(set(vista.roles_permitidos), {Rol.ADMINISTRADOR, Rol.DESARROLLADOR})

    def test_coordinador_y_proveedor_reciben_403_sin_cambiar_datos(self):
        registros = RegistroBitacora.objects.count()
        datos_post = {
            "nit": "811.222.333",
            "razon_social": "Intento",
            "estado": Proveedor.Estado.APROBADO,
            "motivo": MOTIVO,
            "enlace": "https://documentos.ejemplo.test/x",
        }
        for usuario in (self.coordinador, self.usuario_proveedor):
            self.client.force_login(usuario)
            for url in self.urls():
                with self.subTest(usuario=usuario.rol, url=url):
                    self.assertEqual(self.client.get(url).status_code, 403)
                    self.assertEqual(self.client.post(url, datos_post).status_code, 403)
        self.assertEqual(RegistroBitacora.objects.count(), registros)
        self.assertEqual(Proveedor.objects.count(), 1)
        self.proveedor_ficha.refresh_from_db()
        self.assertEqual(self.proveedor_ficha.estado, Proveedor.Estado.REGISTRADO)
        self.assertTrue(DocumentoProveedor.objects.filter(pk=self.documento.pk).exists())

    def test_coordinador_y_proveedor_no_descargan_documentos(self):
        """Ni siquiera el usuario del propio proveedor descarga desde la vista interna."""
        url = reverse("proveedores:documento_descargar", args=[self.proveedor_ficha.pk, self.documento.pk])
        for usuario in (self.coordinador, self.usuario_proveedor):
            with self.subTest(usuario=usuario.rol):
                self.client.force_login(usuario)
                respuesta = self.client.get(url)
                self.assertEqual(respuesta.status_code, 403)
                self.assertFalse(respuesta.streaming)
                self.assertNotIn(b"%PDF", respuesta.content)

    def test_sin_sesion_redirige_al_ingreso(self):
        for url in self.urls():
            with self.subTest(url=url):
                respuesta = self.client.get(url)
                self.assertEqual(respuesta.status_code, 302)
                self.assertTrue(respuesta["Location"].startswith(reverse("cuentas:ingresar")))

    def test_usuario_inactivo_recibe_403(self):
        self.administrador.activo = False
        self.administrador.save()
        self.client.force_login(self.administrador)
        self.assertIn(self.client.get(reverse("proveedores:lista")).status_code, (302, 403))

    def test_administrador_y_desarrollador_entran(self):
        for usuario in (self.administrador, self.desarrollador):
            self.client.force_login(usuario)
            for url in self.urls():
                with self.subTest(usuario=usuario.rol, url=url):
                    self.assertEqual(self.client.get(url).status_code, 200)

    def test_documento_de_otro_proveedor_por_url_da_404(self):
        otro = crear_proveedor(razon_social="Otro Proveedor Ficticio")
        self.client.force_login(self.administrador)
        for nombre in ("documento_editar", "documento_eliminar", "documento_descargar"):
            with self.subTest(vista=nombre):
                url = reverse(f"proveedores:{nombre}", args=[otro.pk, self.documento.pk])
                self.assertEqual(self.client.get(url).status_code, 404)

    def test_metodos_no_permitidos(self):
        self.client.force_login(self.administrador)
        for nombre in ("lista", "vencimientos"):
            self.assertEqual(self.client.post(reverse(f"proveedores:{nombre}")).status_code, 405)
        url = reverse("proveedores:documento_descargar", args=[self.proveedor_ficha.pk, self.documento.pk])
        self.assertEqual(self.client.post(url).status_code, 405)

    def test_el_menu_muestra_proveedores_solo_a_administracion(self):
        self.client.force_login(self.administrador)
        self.assertContains(self.client.get(reverse("inicio")), reverse("proveedores:lista"))
        self.client.force_login(self.coordinador)
        self.assertNotContains(self.client.get(reverse("inicio")), reverse("proveedores:lista"))

    def test_los_servicios_rechazan_a_quien_no_es_administracion(self):
        from django.core.exceptions import PermissionDenied

        for usuario in (self.coordinador, self.usuario_proveedor):
            with self.subTest(usuario=usuario.rol):
                with self.assertRaises(PermissionDenied):
                    servicios.guardar_proveedor(self.proveedor_ficha, actor=usuario, motivo=MOTIVO)
                with self.assertRaises(PermissionDenied):
                    servicios.cambiar_estado(self.proveedor_ficha, Proveedor.Estado.APROBADO, actor=usuario, motivo=MOTIVO)
                with self.assertRaises(PermissionDenied):
                    servicios.eliminar_documento(self.documento, actor=usuario, motivo=MOTIVO)
        self.assertTrue(DocumentoProveedor.objects.filter(pk=self.documento.pk).exists())
