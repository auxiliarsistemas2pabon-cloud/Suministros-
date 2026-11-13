"""PDF privados del portal y separación entre proveedores."""

from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.test import Client, TestCase
from django.urls import resolve, reverse
from django.utils import timezone

from bitacora.models import RegistroBitacora
from cuentas.models import Rol
from cuentas.tests.utilidades import crear_usuario
from portal import servicios
from proveedores import servicios as proveedores_servicios
from proveedores.models import DocumentoProveedor, EnvioProveedor, Proveedor
from proveedores.tests.utilidades import CONTENIDO_PDF, MOTIVO, MediaTemporal, pdf, tipo_documento


class EnviosPortalTests(MediaTemporal, TestCase):
    def setUp(self):
        super().setUp()
        self.usuario = crear_usuario(Rol.PROVEEDOR)
        self.otro = crear_usuario(Rol.PROVEEDOR, correo="otro@ejemplo.test")
        self.admin = crear_usuario(Rol.ADMINISTRADOR)
        self.tipo = tipo_documento()
        self.hoy = timezone.localdate()
        self.url = reverse("portal:envio_nuevo")
        self.datos = {"tipo": self.tipo.pk, "fecha_expedicion": self.hoy - timedelta(days=1),
                      "fecha_vencimiento": self.hoy + timedelta(days=30)}

    def enviar(self, actor=None, **cambios):
        datos = {"actor": actor or self.usuario, "tipo": self.tipo,
                 "fecha_expedicion": self.datos["fecha_expedicion"],
                 "fecha_vencimiento": self.datos["fecha_vencimiento"], "archivo": pdf(), **cambios}
        return servicios.enviar_documento(**datos)

    def rutas(self, envio, documento):
        return [reverse("portal:inicio"), self.url, reverse("portal:envio_descargar", args=[envio.pk]),
                reverse("portal:documento_descargar", args=[documento.pk])]

    def documento(self, envio):
        return DocumentoProveedor.objects.create(
            proveedor=envio.proveedor, tipo=envio.tipo, fecha_expedicion=envio.fecha_expedicion,
            fecha_vencimiento=envio.fecha_vencimiento, archivo=envio.archivo.name,
            nombre_archivo=envio.nombre_archivo, cargado_por=self.admin,
        )

    def test_subida_guarda_uuid_estado_actor_y_bitacora(self):
        self.client.force_login(self.usuario)
        respuesta = self.client.post(self.url, {**self.datos, "archivo_pdf": pdf(), "proveedor": self.otro.proveedor_id,
                                              "estado": "aceptado", "revisado_por": self.admin.pk})
        self.assertRedirects(respuesta, reverse("portal:inicio"))
        envio = EnvioProveedor.objects.get()
        self.assertEqual(envio.proveedor, self.usuario.proveedor)
        self.assertEqual(envio.enviado_por, self.usuario)
        self.assertEqual(envio.estado, "pendiente")
        self.assertIsNone(envio.revisado_por)
        self.assertRegex(envio.archivo.name, r"^envios/\d{4}/\d{2}/[0-9a-f-]{36}\.pdf$")
        self.assertEqual(Path(envio.archivo.path).read_bytes(), CONTENIDO_PDF)
        registro = RegistroBitacora.objects.get(accion="envio_proveedor.creado")
        self.assertEqual(registro.actor, self.usuario)
        self.assertEqual(registro.valor_nuevo["estado"], "pendiente")
        self.assertTrue(registro.motivo)
        self.assertFalse(DocumentoProveedor.objects.exists())

    def test_pdf_falso_grande_y_fechas_invalidas_no_dejan_archivos(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        self.client.force_login(self.usuario)
        for datos in (
            {"archivo_pdf": SimpleUploadedFile("falso.pdf", b"imagen")},
            {"archivo_pdf": pdf("documento.txt")},
            {"archivo_pdf": pdf(), "fecha_expedicion": self.hoy + timedelta(days=1)},
            {"archivo_pdf": pdf(), "fecha_vencimiento": ""},
            {"archivo_pdf": pdf(), "fecha_vencimiento": self.hoy - timedelta(days=2)},
        ):
            with self.subTest(datos=datos):
                self.assertEqual(self.client.post(self.url, {**self.datos, **datos}).status_code, 200)
                self.assertFalse(EnvioProveedor.objects.exists())
        with patch("proveedores.archivos.TAMANO_MAXIMO", 5):
            self.assertEqual(self.client.post(self.url, {**self.datos, "archivo_pdf": pdf()}).status_code, 200)
        self.assertEqual(list(Path(settings.MEDIA_ROOT).rglob("*.pdf")), [])

    def test_servicio_valida_fechas_y_borra_pdf_si_falla(self):
        with self.assertRaises(ValidationError):
            self.enviar(fecha_vencimiento=self.hoy - timedelta(days=5))
        self.assertFalse(EnvioProveedor.objects.exists())
        self.assertEqual(list(Path(settings.MEDIA_ROOT).rglob("*.pdf")), [])

    def test_tipo_inactivo_no_se_admite(self):
        self.tipo.activo = False
        self.tipo.save()
        self.client.force_login(self.usuario)
        self.assertEqual(self.client.post(self.url, {**self.datos, "archivo_pdf": pdf()}).status_code, 200)
        with self.assertRaises(ValidationError):
            self.enviar()
        self.assertFalse(EnvioProveedor.objects.exists())

    def test_tipo_sin_vencimiento_permite_fecha_vacia(self):
        self.tipo.requiere_vencimiento = False
        self.tipo.save()
        self.assertIsNone(self.enviar(fecha_vencimiento=None).fecha_vencimiento)

    def test_cada_proveedor_ve_solo_su_ficha_y_envios(self):
        propio, ajeno = self.enviar(), self.enviar(actor=self.otro)
        self.client.force_login(self.usuario)
        respuesta = self.client.get(reverse("portal:inicio"))
        self.assertContains(respuesta, self.usuario.proveedor.nit_formateado)
        self.assertNotContains(respuesta, self.otro.proveedor.nit_formateado)
        self.assertEqual([e.pk for e in respuesta.context["pagina"]], [propio.pk])
        self.assertNotContains(respuesta, reverse("portal:envio_descargar", args=[ajeno.pk]))

    def test_descargas_propias_privadas_y_ajenas_404(self):
        envio = self.enviar()
        documento = self.documento(envio)
        self.client.force_login(self.usuario)
        for nombre, pk in (("envio_descargar", envio.pk), ("documento_descargar", documento.pk)):
            url = reverse("portal:" + nombre, args=[pk])
            respuesta = self.client.get(url)
            self.assertEqual(respuesta.status_code, 200)
            self.assertEqual(b"".join(respuesta.streaming_content), CONTENIDO_PDF)
            self.assertEqual(respuesta["Content-Type"], "application/pdf")
            self.assertEqual(respuesta["X-Content-Type-Options"], "nosniff")
            self.assertIn("attachment", respuesta["Content-Disposition"])
            self.assertIn("private", respuesta["Cache-Control"])
            self.assertIn("no-store", respuesta["Cache-Control"])
            self.client.force_login(self.otro)
            self.assertEqual(self.client.get(url).status_code, 404)
            self.client.force_login(self.usuario)
        interna = reverse("proveedores:documento_descargar", args=[envio.proveedor_id, documento.pk])
        self.assertEqual(self.client.get(interna).status_code, 403)
        for ruta in (f"/media/{envio.archivo.name}", f"/archivos_privados/{envio.archivo.name}"):
            self.assertEqual(self.client.get(ruta).status_code, 404)

    def test_roles_no_proveedores_403_en_todas_las_rutas_privadas(self):
        envio = self.enviar()
        documento = self.documento(envio)
        for actor in (self.admin, crear_usuario(Rol.COORDINADOR), crear_usuario(Rol.DESARROLLADOR)):
            self.client.force_login(actor)
            for url in self.rutas(envio, documento):
                with self.subTest(rol=actor.rol, url=url):
                    self.assertEqual(self.client.get(url).status_code, 403)
                    self.assertEqual(self.client.post(url, {}).status_code, 403)
                    self.assertEqual(resolve(url).func.roles_permitidos, frozenset([Rol.PROVEEDOR]))
            with self.assertRaises(PermissionDenied):
                self.enviar(actor=actor)

    def test_sin_sesion_se_redirige_en_cada_ruta_privada(self):
        envio = self.enviar()
        for ruta in self.rutas(envio, self.documento(envio)):
            respuesta = self.client.get(ruta)
            self.assertEqual(respuesta.status_code, 302)
            self.assertTrue(respuesta["Location"].startswith("/ingresar/?next="))

    def test_inactivo_puede_consultar_historial_pero_no_enviar(self):
        envio = self.enviar()
        Proveedor.objects.filter(pk=self.usuario.proveedor_id).update(estado="inactivo")
        self.client.force_login(self.usuario)
        self.assertEqual(self.client.get(reverse("portal:inicio")).status_code, 200)
        self.assertEqual(self.client.get(reverse("portal:envio_descargar", args=[envio.pk])).status_code, 200)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.assertEqual(self.client.post(self.url, {**self.datos, "archivo_pdf": pdf()}).status_code, 403)
        with self.assertRaises(PermissionDenied):
            self.enviar()

    def test_fallo_de_bitacora_revierte_envio_y_borra_archivo(self):
        with patch("proveedores.servicios.registrar", side_effect=RuntimeError("Fallo simulado")):
            with self.assertRaises(RuntimeError):
                self.enviar()
        self.assertFalse(EnvioProveedor.objects.exists())
        self.assertEqual(list(Path(settings.MEDIA_ROOT).rglob("*.pdf")), [])

    def test_no_admite_transaccion_externa_que_pueda_dejar_pdf_huerfano(self):
        with transaction.atomic(), self.assertRaises(ValidationError):
            self.enviar()
        self.assertEqual(list(Path(settings.MEDIA_ROOT).rglob("*.pdf")), [])

    def test_archivo_compartido_solo_se_borra_al_quitar_ultima_referencia(self):
        envio = self.enviar()
        documento = self.documento(envio)
        ruta = Path(envio.archivo.path)
        with self.captureOnCommitCallbacks(execute=True):
            envio.delete()
        self.assertTrue(ruta.exists())
        with self.captureOnCommitCallbacks(execute=True):
            proveedores_servicios.eliminar_documento(documento, actor=self.admin, motivo=MOTIVO)
        self.assertFalse(ruta.exists())

    def test_archivo_ausente_y_documento_sin_pdf_devuelven_404(self):
        envio = self.enviar()
        Path(envio.archivo.path).unlink()
        self.client.force_login(self.usuario)
        self.assertEqual(self.client.get(reverse("portal:envio_descargar", args=[envio.pk])).status_code, 404)
        documento = self.documento(envio)
        documento.archivo = ""
        documento.enlace = "https://documentos.ejemplo.test/x"
        documento.save()
        self.assertEqual(self.client.get(reverse("portal:documento_descargar", args=[documento.pk])).status_code, 404)

    def test_subida_sin_csrf_no_guarda_y_no_existen_edicion_ni_borrado(self):
        cliente = Client(enforce_csrf_checks=True)
        cliente.force_login(self.usuario)
        self.assertEqual(cliente.post(self.url, {**self.datos, "archivo_pdf": pdf()}).status_code, 403)
        self.assertFalse(EnvioProveedor.objects.exists())
        for accion in ("editar", "borrar", "eliminar"):
            self.assertEqual(self.client.post(f"/portal/envios/1/{accion}/").status_code, 404)

    def test_restricciones_de_estado_y_revision_en_la_base(self):
        envio = self.enviar()
        for cambio in ({"estado": "otro"}, {"estado": "aceptado"}, {"fecha_revision": timezone.now()},
                       {"fecha_vencimiento": self.hoy - timedelta(days=5)}):
            with self.subTest(cambio=cambio), self.assertRaises(IntegrityError), transaction.atomic():
                EnvioProveedor.objects.filter(pk=envio.pk).update(**cambio)
