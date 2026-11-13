from copy import deepcopy
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Value
from django.test import Client, TestCase
from django.urls import reverse

from bitacora.models import RegistroBitacora
from bitacora.servicios import registrar
from compras import cotizacion_servicios, oferta_servicios, proveedor_unico_servicios as servicios, tests_cotizaciones
from compras.models import CausalProveedorUnico, Cotizacion, PdfProveedorUnico, RevisionProveedorUnico, TarifaImpuesto
from parametros.catalogo import EVIDENCIA_UNICO_OBLIGATORIA, MIN_JUSTIFICACION_UNICO
from parametros.models import Parametro
from parametros.servicios import cambiar_valor
from proveedores import archivos
from proveedores.tests.utilidades import MediaTemporal, crear_proveedor, pdf

MOTIVO = "Caso ficticio justificado por disponibilidad exclusiva del insumo"


class ProveedorUnicoTests(MediaTemporal, TestCase):
    def setUp(self):
        super().setUp()
        tests_cotizaciones.CotizacionesTests.setUp(self)
        self.cotizacion = cotizacion_servicios.crear_cotizacion(necesidad=self.necesidad, fecha=self.fecha, tipo=self.tipo,
            objeto="Cotización ficticia para proveedor único", lineas=[{"descripcion": "Insumo", "unidad": self.unidad, "cantidad": Decimal(2)}],
            invitados=[self.ficha], actor=self.admin, motivo=MOTIVO)
        self.causal = CausalProveedorUnico.objects.get(nombre="Exclusividad")
        self.tarifa = TarifaImpuesto.objects.get(nombre="Exento/No gravado")
        self.oferta = self.crear_oferta(self.cotizacion.invitados.get())
        self.url = reverse("compras:proveedor_unico", args=[self.cotizacion.pk])

    def calificar(self, valores=None):
        return tests_cotizaciones.CotizacionesTests.calificar(self, valores)

    def asignaciones(self, cantidades=None, justificaciones=None):
        return tests_cotizaciones.CotizacionesTests.asignaciones(self, cantidades, justificaciones)

    def decidir(self, **kwargs):
        return tests_cotizaciones.CotizacionesTests.decidir(self, **kwargs)

    def crear_oferta(self, invitado):
        return oferta_servicios.guardar_oferta(self.cotizacion, invitado, contacto_nombre="Contacto ficticio",
            contacto_correo="contacto@ejemplo.test", contacto_telefono="601 555 0100", fecha=self.fecha,
            precios=[{"linea": self.cotizacion.lineas.get().pk, "precio_unitario": Decimal(10), "tarifa": self.tarifa}], actor=self.admin, motivo=MOTIVO)

    def segunda_oferta(self):
        invitado = oferta_servicios.invitar_proveedor(self.cotizacion, crear_proveedor(), actor=self.admin, motivo=MOTIVO)
        return self.crear_oferta(invitado)

    def guardar(self, **cambios):
        datos = dict(proveedor_unico=True, causal=self.causal, justificacion=MOTIVO, actor=self.admin, motivo=MOTIVO)
        datos.update(cambios)
        self.cotizacion = servicios.guardar_caso(self.cotizacion, **datos)
        return self.cotizacion

    def parametro(self, clave, valor):
        return cambiar_valor(Parametro.objects.get(clave=clave), valor, actor=self.admin, motivo=MOTIVO)

    def post(self, **cambios):
        datos = {"proveedor_unico": "on", "causal": self.causal.pk, "justificacion": MOTIVO,
            "motivo": MOTIVO, "revision_esperada": 0}
        datos.update(cambios)
        return datos

    def test_sugerencia_con_una_oferta_no_escribe_al_abrir(self):
        self.client.force_login(self.admin)
        respuesta = self.client.get(self.url)
        self.assertEqual(respuesta.status_code, 200)
        self.assertTrue(respuesta.context["formulario"]["proveedor_unico"].value())
        self.cotizacion.refresh_from_db()
        self.assertFalse(self.cotizacion.proveedor_unico)
        self.assertFalse(RevisionProveedorUnico.objects.exists())
        self.assertFalse(RegistroBitacora.objects.filter(accion__startswith="unico.").exists())

    def test_marcar_desmarcar_guarda_actor_motivo_y_foto(self):
        caso = self.guardar(actor=self.dev)
        self.assertTrue(caso.proveedor_unico)
        self.assertEqual(caso.oferta_unica_datos["proveedor_id"], self.ficha.pk)
        foto = deepcopy(caso.revisiones_proveedor_unico.get().contenido)
        self.causal.nombre = "Causal renombrada ficticia"
        servicios.guardar_causal(self.causal, actor=self.admin, motivo=MOTIVO)
        caso.refresh_from_db()
        self.assertEqual(caso.causal_unico_nombre, "Exclusividad")
        caso = self.guardar(proveedor_unico=False)
        self.assertIsNone(caso.causal_proveedor_unico_id)
        self.assertEqual(caso.justificacion_proveedor_unico, "")
        revision = caso.revisiones_proveedor_unico.get(numero=1)
        self.assertEqual(revision.actor, self.dev)
        self.assertEqual(revision.motivo, MOTIVO)
        self.assertEqual(revision.contenido, foto)
        self.assertTrue(RegistroBitacora.objects.filter(accion="unico.marcado", actor=self.dev).exists())
        self.assertTrue(RegistroBitacora.objects.filter(accion="unico.desmarcado", motivo=MOTIVO).exists())

    def test_justificacion_vacia_espacios_y_minimo_configurable(self):
        self.parametro(MIN_JUSTIFICACION_UNICO, "5")
        for texto in ["", " \n\t ", "abc", "a          b"]:
            with self.subTest(texto=texto), self.assertRaises(ValidationError):
                self.guardar(justificacion=texto)
        caso = self.guardar(justificacion="  abc   de  ")
        self.assertEqual(caso.justificacion_proveedor_unico, "abc de")
        self.assertEqual(caso.reglas_proveedor_unico["min_caracteres"], 5)

    def test_parametro_no_permite_minimo_cero_y_servicio_detecta_configuracion_corrupta(self):
        with self.assertRaises(ValidationError):
            self.parametro(MIN_JUSTIFICACION_UNICO, "0")
        Parametro.objects.filter(clave=MIN_JUSTIFICACION_UNICO).update(valor="0")
        with self.assertRaises(ValidationError):
            self.guardar()

    def test_causal_obligatoria_activa_y_nombre_unico(self):
        with self.assertRaises(ValidationError):
            self.guardar(causal=None)
        self.causal.activo = False
        servicios.guardar_causal(self.causal, actor=self.admin, motivo=MOTIVO)
        with self.assertRaises(ValidationError):
            self.guardar()
        with self.assertRaises(ValidationError):
            servicios.guardar_causal(CausalProveedorUnico(nombre=" EXCLUSIVIDAD "), actor=self.admin, motivo=MOTIVO)
        otra = servicios.guardar_causal(CausalProveedorUnico(nombre="Otra causal ficticia", descripcion="Descripción", orden=9), actor=self.admin, motivo=MOTIVO)
        self.assertTrue(otra.activo)

    def test_dos_ofertas_no_sugieren_ni_permiten_marcar_caso(self):
        self.segunda_oferta()
        self.client.force_login(self.admin)
        self.assertFalse(self.client.get(self.url).context["formulario"]["proveedor_unico"].value())
        with self.assertRaises(ValidationError):
            self.guardar()
        foto = servicios.validar_para_decidir(self.cotizacion, actor=self.admin)
        self.assertFalse(foto["proveedor_unico"])
        self.assertEqual(foto["numero_ofertas"], 2)

    def test_sin_ofertas_no_permite_caso_ni_decision(self):
        otra = cotizacion_servicios.crear_cotizacion(necesidad=self.necesidad, fecha=self.fecha, tipo=self.tipo,
            objeto="Sin ofertas", lineas=[{"descripcion": "Insumo", "unidad": self.unidad, "cantidad": 1}],
            invitados=[self.ficha], actor=self.admin, motivo=MOTIVO)
        with self.assertRaises(ValidationError):
            servicios.guardar_caso(otra, proveedor_unico=True, causal=self.causal, justificacion=MOTIVO, actor=self.admin, motivo=MOTIVO)
        with self.assertRaises(ValidationError):
            servicios.validar_para_decidir(otra, actor=self.admin)

    def test_una_oferta_no_cierra_omitiendo_o_desmarcando_el_caso(self):
        with self.assertRaises(ValidationError):
            servicios.validar_para_decidir(self.cotizacion, actor=self.admin)
        self.guardar()
        self.guardar(proveedor_unico=False)
        with self.assertRaises(ValidationError):
            servicios.validar_para_decidir(self.cotizacion, actor=self.admin)

    def test_decision_valida_con_foto_y_reglas_vigentes_sin_cambiar_estado(self):
        self.guardar()
        foto = servicios.validar_para_decidir(self.cotizacion, actor=self.admin)
        self.assertEqual(foto["causal"], "Exclusividad")
        self.assertEqual(foto["oferta"]["nit"], self.ficha.nit)
        self.cotizacion.refresh_from_db()
        self.assertEqual(self.cotizacion.estado, "borrador")
        self.parametro(MIN_JUSTIFICACION_UNICO, "200")
        with self.assertRaises(ValidationError):
            servicios.validar_para_decidir(self.cotizacion, actor=self.admin)
        self.cotizacion.refresh_from_db()
        self.assertEqual(self.cotizacion.reglas_proveedor_unico["min_caracteres"], 20)

    def test_evidencia_opcional_y_obligatoria_segun_parametro(self):
        self.guardar()
        self.parametro(EVIDENCIA_UNICO_OBLIGATORIA, "true")
        with self.assertRaises(ValidationError):
            servicios.validar_para_decidir(self.cotizacion, actor=self.admin)
        with self.assertRaises(ValidationError):
            self.guardar()
        caso = self.guardar(archivo=pdf())
        self.assertIsNotNone(caso.pdf_proveedor_unico_id)
        servicios.validar_para_decidir(caso, actor=self.admin)
        with self.assertRaises(ValidationError):
            self.guardar(quitar_pdf=True)

    def test_segunda_oferta_invalida_caso_confirmado_hasta_desmarcarlo(self):
        self.guardar()
        self.segunda_oferta()
        with self.assertRaises(ValidationError):
            servicios.validar_para_decidir(self.cotizacion, actor=self.admin)
        self.guardar(proveedor_unico=False)
        self.assertFalse(servicios.validar_para_decidir(self.cotizacion, actor=self.admin)["proveedor_unico"])

    def test_revision_esperada_impide_sobrescribir_otro_guardado(self):
        self.guardar(revision_esperada=0)
        with self.assertRaises(ValidationError):
            self.guardar(revision_esperada=0, proveedor_unico=False)
        self.cotizacion.refresh_from_db()
        self.assertTrue(self.cotizacion.proveedor_unico)
        self.assertEqual(self.cotizacion.revision_proveedor_unico, 1)

    def test_modelo_no_admite_decidida_sin_validar_y_actualizacion_masiva_bloqueada(self):
        self.cotizacion.estado = "decidida"
        with self.assertRaises(ValidationError):
            self.cotizacion.save(update_fields=["estado"])
        for datos in [{"estado": "decidida"}, {"estado": Value("decidida")}, {"proveedor_unico": True}, {"oferta_unica_datos": {}}]:
            with self.assertRaises(ValidationError):
                Cotizacion.objects.filter(pk=self.cotizacion.pk).update(**datos)
        self.guardar()
        self.cotizacion.estado = "decidida"
        self.cotizacion.save(update_fields=["estado"])
        self.cotizacion.refresh_from_db()
        self.assertEqual(self.cotizacion.estado, "decidida")

    def test_decision_no_sobrescribe_caso_con_datos_invalidos_y_usa_estado_persistido(self):
        atrasada = Cotizacion.objects.get(pk=self.cotizacion.pk)
        self.guardar()
        self.cotizacion.estado = "decidida"
        self.cotizacion.justificacion_proveedor_unico = " "
        with self.assertRaises(ValidationError):
            self.cotizacion.save()
        atrasada.estado = "decidida"
        atrasada.save(update_fields=["estado"])
        atrasada.refresh_from_db()
        self.assertTrue(atrasada.proveedor_unico)
        self.assertEqual(atrasada.estado, "decidida")

    def test_estados_finales_impiden_modificar_caso(self):
        self.guardar()
        self.client.force_login(self.admin)
        for estado in ["decidida", "anulada"]:
            self.cotizacion.estado = estado
            self.cotizacion.save(update_fields=["estado"])
            with self.assertRaises(ValidationError):
                self.guardar(proveedor_unico=False)
            respuesta = self.client.get(self.url)
            self.assertFalse(respuesta.context["editable"])
            self.assertEqual(self.client.post(self.url, self.post()).status_code, 302)

    def test_pdf_reemplazado_retirado_y_caso_desmarcado_conservan_historial(self):
        self.guardar(archivo=pdf("original.pdf"))
        anterior = self.cotizacion.pdf_proveedor_unico
        self.guardar(archivo=pdf("reemplazo.pdf"))
        self.guardar(quitar_pdf=True)
        self.guardar(proveedor_unico=False)
        archivos.borrar_sin_referencias(anterior.archivo.name)
        self.assertTrue(Path(anterior.archivo.path).exists())
        self.assertEqual(PdfProveedorUnico.objects.count(), 2)
        self.assertEqual(self.cotizacion.revisiones_proveedor_unico.get(numero=1).pdf_id, anterior.pk)
        self.assertIsNone(self.cotizacion.pdf_proveedor_unico_id)
        for objeto in [anterior, self.cotizacion.revisiones_proveedor_unico.first()]:
            with self.assertRaises(ValidationError):
                objeto.save()
            with self.assertRaises(ValidationError):
                objeto.delete()

    def test_fallo_auditoria_revierte_caso_y_elimina_solo_pdf_nuevo(self):
        self.guardar(archivo=pdf("conservado.pdf"))
        anterior = self.cotizacion.pdf_proveedor_unico
        def fallo(accion, **kwargs):
            if accion == "unico.modificado":
                raise RuntimeError("Fallo ficticio de auditoría")
            return registrar(accion, **kwargs)
        with patch("compras.proveedor_unico_servicios.registrar", side_effect=fallo), self.assertRaises(RuntimeError):
            self.guardar(archivo=pdf("fallido.pdf"))
        self.cotizacion.refresh_from_db()
        self.assertEqual(self.cotizacion.pdf_proveedor_unico_id, anterior.pk)
        self.assertEqual(self.cotizacion.revisiones_proveedor_unico.count(), 1)
        self.assertEqual(len(list(Path(settings.MEDIA_ROOT).rglob("*.pdf"))), 1)

    def test_pdf_invalido_y_transaccion_externa_no_dejan_archivos(self):
        grande = pdf()
        grande.size = archivos.TAMANO_MAXIMO + 1
        for archivo in [pdf("no.exe"), pdf("no.pdf", b"no es PDF"), grande]:
            with self.assertRaises(ValidationError):
                self.guardar(archivo=archivo)
        with self.assertRaises(ValidationError), transaction.atomic():
            self.guardar(archivo=pdf())
        with self.assertRaises(ValidationError):
            self.guardar(archivo=pdf(), quitar_pdf=True)
        self.assertFalse(list(Path(settings.MEDIA_ROOT).rglob("*.pdf")))

    def test_validacion_fallida_tras_cargar_pdf_compensa_el_archivo(self):
        with self.assertRaises(ValidationError):
            self.guardar(archivo=pdf(), justificacion=" ")
        self.assertFalse(PdfProveedorUnico.objects.exists())
        self.assertFalse(RevisionProveedorUnico.objects.exists())
        self.assertFalse(list(Path(settings.MEDIA_ROOT).rglob("*.pdf")))

    def test_servicios_exigen_permisos_y_motivo(self):
        for actor in [self.coordinador, self.usuario_proveedor, AnonymousUser()]:
            with self.assertRaises(PermissionDenied):
                self.guardar(actor=actor)
            with self.assertRaises(PermissionDenied):
                servicios.validar_para_decidir(self.cotizacion, actor=actor)
            with self.assertRaises(PermissionDenied):
                servicios.guardar_causal(self.causal, actor=actor, motivo=MOTIVO)
        with self.assertRaises(ValidationError):
            self.guardar(motivo=" ")

    def test_pantallas_post_y_csrf(self):
        self.client.force_login(self.admin)
        respuesta = self.client.post(self.url, self.post(justificacion=" "))
        self.assertEqual(respuesta.status_code, 200)
        self.assertFalse(RevisionProveedorUnico.objects.exists())
        self.assertEqual(self.client.post(self.url, self.post()).status_code, 302)
        csrf = Client(enforce_csrf_checks=True)
        csrf.force_login(self.admin)
        self.assertEqual(csrf.post(self.url, self.post()).status_code, 403)
        catalogo = reverse("compras:proveedor_unico_causales")
        self.assertEqual(self.client.post(catalogo, {"nombre": "Nueva causal ficticia", "orden": 5, "activo": "on", "motivo": MOTIVO}).status_code, 302)
        self.assertTrue(CausalProveedorUnico.objects.filter(nombre="Nueva causal ficticia").exists())

    def test_pdf_privado_acotado_a_cotizacion_y_rol(self):
        self.guardar(archivo=pdf("evidencia.pdf"))
        url = reverse("compras:proveedor_unico_pdf", args=[self.cotizacion.pk, self.cotizacion.pdf_proveedor_unico_id])
        historico = self.cotizacion.revisiones_proveedor_unico.get()
        historial = reverse("compras:proveedor_unico_revision", args=[self.cotizacion.pk, historico.pk])
        for actor in [self.admin, self.dev]:
            self.client.force_login(actor)
            respuesta = self.client.get(url)
            self.assertEqual(respuesta.status_code, 200)
            self.assertEqual(respuesta["X-Content-Type-Options"], "nosniff")
            self.assertIn("no-store", respuesta["Cache-Control"])
            self.assertTrue(b"".join(respuesta.streaming_content).startswith(b"%PDF-"))
            self.assertContains(self.client.get(historial), "Exclusividad")
        self.assertEqual(self.client.get(reverse("compras:proveedor_unico_pdf", args=[self.cotizacion.pk + 999, self.cotizacion.pdf_proveedor_unico_id])).status_code, 404)
        self.assertEqual(self.client.get(reverse("compras:proveedor_unico_revision", args=[self.cotizacion.pk + 999, historico.pk])).status_code, 404)
        rutas = [url, historial, self.url, reverse("compras:proveedor_unico_causales")]
        for actor in [self.coordinador, self.usuario_proveedor]:
            self.client.force_login(actor)
            for ruta in rutas:
                self.assertEqual(self.client.get(ruta).status_code, 403)
        self.client.logout()
        self.assertEqual(self.client.get(url).status_code, 302)
