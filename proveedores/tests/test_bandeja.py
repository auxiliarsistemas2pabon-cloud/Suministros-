"""A15: revisión atómica, reutilización de PDF y permisos de cada ruta."""

from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from unittest import skipUnless
from unittest.mock import patch

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, connection, connections, transaction
from django.test import Client, TestCase, TransactionTestCase
from django.urls import resolve, reverse
from django.utils import timezone

from bitacora.models import RegistroBitacora
from cuentas.models import ROLES_ADMIN, Rol
from cuentas.tests.utilidades import crear_usuario
from parametros.catalogo import CONSERVAR_PDF_DESCARTADO
from parametros.models import Parametro
from proveedores import servicios
from proveedores.models import DocumentoProveedor, EnvioProveedor
from proveedores.tests.utilidades import CONTENIDO_PDF, MOTIVO, MediaTemporal, pdf, tipo_documento


class BandejaTests(MediaTemporal, TestCase):
    def setUp(self):
        super().setUp()
        self.admin = crear_usuario(Rol.ADMINISTRADOR)
        self.dev = crear_usuario(Rol.DESARROLLADOR)
        self.usuario = crear_usuario(Rol.PROVEEDOR)
        self.coordinador = crear_usuario(Rol.COORDINADOR)
        self.tipo = tipo_documento()
        self.hoy = timezone.localdate()
        self.envio = self.crear()

    def crear(self, actor=None, **cambios):
        return servicios.crear_envio(
            proveedor=self.usuario.proveedor, actor=actor or self.usuario, tipo=cambios.pop("tipo", self.tipo),
            fecha_expedicion=self.hoy - timedelta(days=1), fecha_vencimiento=self.hoy + timedelta(days=30),
            archivo=cambios.pop("archivo", pdf()), motivo=MOTIVO, **cambios,
        )

    def revisar(self, aceptar=True, **opciones):
        return servicios.revisar_envio(opciones.pop("envio", self.envio), aceptar=aceptar,
                                      actor=opciones.pop("actor", self.admin), motivo=opciones.pop("motivo", MOTIVO))

    def url(self, nombre):
        return reverse("proveedores:" + nombre, args=[] if nombre in ("bandeja", "envio_manual") else [self.envio.pk])

    def test_aceptar_reutiliza_ruta_y_no_duplica_pdf(self):
        ruta = self.envio.archivo.name
        nombres_antes = set(Path(settings.MEDIA_ROOT).rglob("*.pdf"))
        revisado = self.revisar()
        documento = DocumentoProveedor.objects.get()
        self.assertEqual(revisado.estado, "aceptado")
        self.assertEqual(revisado.documento, documento)
        self.assertEqual(documento.archivo.name, ruta)
        self.assertEqual(documento.nombre_archivo, self.envio.nombre_archivo)
        self.assertEqual(documento.proveedor, self.usuario.proveedor)
        self.assertEqual(documento.fecha_expedicion, self.envio.fecha_expedicion)
        self.assertEqual(documento.fecha_vencimiento, self.envio.fecha_vencimiento)
        self.assertEqual(revisado.revisado_por, self.admin)
        self.assertIsNotNone(revisado.fecha_revision)
        self.assertEqual(set(Path(settings.MEDIA_ROOT).rglob("*.pdf")), nombres_antes)
        registro = RegistroBitacora.objects.get(accion="envio_proveedor.aceptado")
        self.assertEqual(registro.valor_anterior["estado"], "pendiente")
        self.assertEqual(registro.valor_nuevo["estado"], "aceptado")
        self.assertEqual(registro.valor_nuevo["documento"]["id"], documento.pk)
        self.assertEqual(registro.actor, self.admin)
        self.assertEqual(registro.motivo, MOTIVO)

    def test_repetir_aceptar_o_descartar_no_crea_segundo_documento(self):
        self.revisar()
        for aceptar in (True, False):
            with self.subTest(aceptar=aceptar), self.assertRaisesMessage(ValidationError, "ya fue revisado"):
                self.revisar(aceptar)
        self.assertEqual(DocumentoProveedor.objects.count(), 1)
        self.assertEqual(RegistroBitacora.objects.filter(accion="envio_proveedor.aceptado").count(), 1)

    def test_descartar_conserva_pdf_por_defecto_y_guarda_revision(self):
        ruta = Path(self.envio.archivo.path)
        with self.captureOnCommitCallbacks(execute=True):
            resultado = self.revisar(False)
        self.assertTrue(ruta.exists())
        self.assertTrue(resultado.archivo)
        self.assertEqual(resultado.estado, "descartado")
        self.assertEqual(resultado.revisado_por, self.admin)
        self.assertEqual(resultado.motivo, MOTIVO)
        self.assertFalse(DocumentoProveedor.objects.exists())
        with self.assertRaises(ValidationError):
            self.revisar(True)

    def test_descartar_sin_retencion_borra_solo_despues_del_commit(self):
        Parametro.objects.filter(clave=CONSERVAR_PDF_DESCARTADO).update(valor="false")
        ruta = Path(self.envio.archivo.path)
        with self.captureOnCommitCallbacks(execute=True):
            resultado = self.revisar(False)
            self.assertTrue(ruta.exists())
        self.assertFalse(ruta.exists())
        self.assertFalse(resultado.archivo)
        self.assertTrue(EnvioProveedor.objects.filter(pk=resultado.pk).exists())
        registro = RegistroBitacora.objects.get(accion="envio_proveedor.descartado")
        self.assertTrue(registro.valor_anterior["archivo"])
        self.assertEqual(registro.valor_nuevo["archivo"], "")

    def test_rollback_del_descarte_conserva_estado_y_archivo(self):
        Parametro.objects.filter(clave=CONSERVAR_PDF_DESCARTADO).update(valor="false")
        ruta = Path(self.envio.archivo.path)
        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            with self.assertRaises(RuntimeError), transaction.atomic():
                self.revisar(False)
                raise RuntimeError("Fallo posterior")
        self.assertFalse(callbacks)
        self.envio.refresh_from_db()
        self.assertEqual(self.envio.estado, "pendiente")
        self.assertTrue(ruta.exists())

    def test_fallo_auditoria_revierte_aceptacion_y_no_borra_original(self):
        ruta = Path(self.envio.archivo.path)
        registrar_real = servicios.registrar

        def fallar(accion, **kwargs):
            if accion == "envio_proveedor.aceptado":
                raise RuntimeError("Fallo simulado")
            return registrar_real(accion, **kwargs)

        with patch.object(servicios, "registrar", side_effect=fallar), self.assertRaises(RuntimeError):
            self.revisar()
        self.envio.refresh_from_db()
        self.assertEqual(self.envio.estado, "pendiente")
        self.assertIsNone(self.envio.documento_id)
        self.assertFalse(DocumentoProveedor.objects.exists())
        self.assertTrue(ruta.exists())

    def test_motivo_obligatorio_para_ambas_decisiones(self):
        for aceptar in (True, False):
            with self.assertRaises(ValidationError):
                self.revisar(aceptar, motivo=" ")
        self.assertFalse(DocumentoProveedor.objects.exists())

    def test_pdf_ausente_o_manipulado_no_se_acepta(self):
        ruta = Path(self.envio.archivo.path)
        ruta.write_bytes(b"NO ES PDF")
        with self.assertRaises(ValidationError):
            self.revisar()
        ruta.unlink()
        with self.assertRaises(ValidationError):
            self.revisar()
        self.assertFalse(DocumentoProveedor.objects.exists())

    def test_documento_aceptado_no_se_borra_rompiendo_historial(self):
        documento = self.revisar().documento
        with self.assertRaisesMessage(ValidationError, "envío aceptado"):
            servicios.eliminar_documento(documento, actor=self.admin, motivo=MOTIVO)
        self.assertTrue(DocumentoProveedor.objects.filter(pk=documento.pk).exists())

    def test_carga_manual_registra_responsable_y_no_aprueba(self):
        self.client.force_login(self.admin)
        respuesta = self.client.post(self.url("envio_manual"), {
            "proveedor": self.usuario.proveedor_id, "tipo": self.tipo.pk,
            "fecha_expedicion": self.hoy, "fecha_vencimiento": self.hoy + timedelta(days=5),
            "archivo_pdf": pdf(), "motivo": MOTIVO, "estado": "aceptado",
        })
        nuevo = EnvioProveedor.objects.exclude(pk=self.envio.pk).get()
        self.assertRedirects(respuesta, reverse("proveedores:envio_detalle", args=[nuevo.pk]))
        self.assertEqual(nuevo.enviado_por, self.admin)
        self.assertEqual(nuevo.estado, "pendiente")
        self.assertFalse(DocumentoProveedor.objects.exists())

    def test_carga_manual_invalida_no_deja_archivos(self):
        self.client.force_login(self.admin)
        for cambios in ({"motivo": ""}, {"archivo_pdf": pdf("no.txt")}):
            datos = {"proveedor": self.usuario.proveedor_id, "tipo": self.tipo.pk,
                     "fecha_expedicion": self.hoy, "fecha_vencimiento": self.hoy + timedelta(days=5),
                     "archivo_pdf": pdf(), "motivo": MOTIVO, **cambios}
            self.assertEqual(self.client.post(self.url("envio_manual"), datos).status_code, 200)
        self.assertEqual(EnvioProveedor.objects.count(), 1)
        self.assertEqual(len(list(Path(settings.MEDIA_ROOT).rglob("*.pdf"))), 1)

    def test_roles_no_autorizados_403_en_cada_ruta_get_y_post(self):
        rutas = [self.url(n) for n in ("bandeja", "envio_manual", "envio_detalle", "envio_descargar", "envio_aceptar", "envio_descartar")]
        for actor in (self.usuario, self.coordinador):
            self.client.force_login(actor)
            for ruta in rutas:
                with self.subTest(rol=actor.rol, ruta=ruta):
                    self.assertEqual(self.client.get(ruta).status_code, 403)
                    self.assertEqual(self.client.post(ruta, {"motivo": MOTIVO}).status_code, 403)
                    self.assertEqual(resolve(ruta).func.roles_permitidos, frozenset(ROLES_ADMIN))
            with self.assertRaises(PermissionDenied):
                self.revisar(actor=actor)
        self.assertFalse(DocumentoProveedor.objects.exists())

    def test_anonimos_redirigidos_y_lecturas_admin_y_dev_admitidas(self):
        nombres = ("bandeja", "envio_manual", "envio_detalle", "envio_descargar", "envio_aceptar", "envio_descartar")
        for nombre in nombres:
            self.assertEqual(self.client.get(self.url(nombre)).status_code, 302)
        for actor in (self.admin, self.dev):
            self.client.force_login(actor)
            for nombre in nombres:
                respuesta = self.client.get(self.url(nombre))
                self.assertEqual(respuesta.status_code, 405 if nombre in ("envio_aceptar", "envio_descartar") else 200)
                if respuesta.streaming:
                    b"".join(respuesta.streaming_content)

    def test_bandeja_filtra_por_nit_tipo_fechas_estado_y_proveedor(self):
        otro_tipo = tipo_documento("Documento alterno")
        otro = self.crear(tipo=otro_tipo)
        self.revisar()
        self.client.force_login(self.admin)
        respuesta = self.client.get(self.url("bandeja"))
        self.assertEqual([e.pk for e in respuesta.context["pagina"]], [otro.pk])
        datos = {"q": self.usuario.proveedor.nit_formateado, "proveedor": self.usuario.proveedor_id,
                 "tipo": self.tipo.pk, "estado": "aceptado", "desde": self.hoy, "hasta": self.hoy}
        respuesta = self.client.get(self.url("bandeja"), datos)
        self.assertEqual([e.pk for e in respuesta.context["pagina"]], [self.envio.pk])
        self.assertEqual(self.client.get(self.url("bandeja"), {"estado": ""}).context["pagina"].paginator.count, 2)
        self.assertEqual(self.client.get(self.url("bandeja"), {"desde": self.hoy + timedelta(days=1)}).context["pagina"].paginator.count, 0)
        respuesta = self.client.get(self.url("bandeja"), {"desde": self.hoy, "hasta": self.hoy - timedelta(days=1)})
        self.assertTrue(respuesta.context["filtro"].errors)
        self.assertEqual(respuesta.context["pagina"].paginator.count, 0)

    def test_revision_http_con_motivo_y_csrf(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.post(self.url("envio_aceptar"), {"motivo": ""}).status_code, 200)
        cliente = Client(enforce_csrf_checks=True)
        cliente.force_login(self.admin)
        self.assertEqual(cliente.post(self.url("envio_aceptar"), {"motivo": MOTIVO}).status_code, 403)
        self.assertEqual(self.client.post(self.url("envio_aceptar"), {"motivo": MOTIVO}).status_code, 302)
        self.assertEqual(self.client.post(self.url("envio_aceptar"), {"motivo": MOTIVO}).status_code, 200)
        self.assertEqual(DocumentoProveedor.objects.count(), 1)

    def test_descarga_protegida_y_descarte_sin_archivo_da_404(self):
        self.client.force_login(self.admin)
        respuesta = self.client.get(self.url("envio_descargar"))
        self.assertEqual(b"".join(respuesta.streaming_content), CONTENIDO_PDF)
        self.assertEqual(respuesta["X-Content-Type-Options"], "nosniff")
        self.assertIn("attachment", respuesta["Content-Disposition"])
        self.assertIn("private", respuesta["Cache-Control"])
        self.assertIn("no-store", respuesta["Cache-Control"])
        Parametro.objects.filter(clave=CONSERVAR_PDF_DESCARTADO).update(valor="false")
        with self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(self.client.post(self.url("envio_descartar"), {"motivo": MOTIVO}).status_code, 302)
        self.assertEqual(self.client.get(self.url("envio_descargar")).status_code, 404)

    def test_base_impide_documento_en_pendiente_y_pdf_vacio(self):
        for cambios in ({"archivo": ""}, {"estado": "aceptado", "revisado_por": self.admin, "fecha_revision": timezone.now()}):
            with self.assertRaises(IntegrityError), transaction.atomic():
                EnvioProveedor.objects.filter(pk=self.envio.pk).update(**cambios)


@skipUnless(connection.vendor == "postgresql", "La prueba de bloqueos concurrentes requiere PostgreSQL.")
class RevisionConcurrenteTests(MediaTemporal, TransactionTestCase):
    def test_dos_aceptaciones_simultaneas_crean_un_solo_documento(self):
        admin = crear_usuario(Rol.ADMINISTRADOR)
        usuario = crear_usuario(Rol.PROVEEDOR)
        tipo = tipo_documento()
        hoy = timezone.localdate()
        envio = servicios.crear_envio(proveedor=usuario.proveedor, actor=usuario, tipo=tipo,
                                      fecha_expedicion=hoy, fecha_vencimiento=hoy + timedelta(days=10),
                                      archivo=pdf(), motivo=MOTIVO)
        sincronizar = Barrier(2)

        def aceptar():
            from cuentas.models import Usuario

            try:
                actor = Usuario.objects.get(pk=admin.pk)
                copia = EnvioProveedor.objects.get(pk=envio.pk)
                sincronizar.wait(timeout=15)
                try:
                    servicios.revisar_envio(copia, aceptar=True, actor=actor, motivo=MOTIVO)
                    return "aceptado"
                except ValidationError:
                    return "rechazado"
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as ejecutor:
            futuros = [ejecutor.submit(aceptar) for _ in range(2)]
            resultados = [f.result(timeout=30) for f in futuros]
        self.assertCountEqual(resultados, ["aceptado", "rechazado"])
        self.assertEqual(DocumentoProveedor.objects.count(), 1)
        self.assertEqual(RegistroBitacora.objects.filter(accion="envio_proveedor.aceptado").count(), 1)
