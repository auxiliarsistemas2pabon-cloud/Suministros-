"""GDS-PRY-05: aprobación, cantidad autorizada y ajustes posteriores a la aprobación."""

from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.urls import reverse
from django.utils import timezone

from bitacora.models import RegistroBitacora
from parametros.catalogo import APROBACIONES_REQUERIDAS
from parametros.models import Parametro
from proyecciones import servicios
from proyecciones.models import (
    CAMPOS_CANTIDADES_MENSUALES,
    Ajuste,
    AprobacionProyeccion,
    Linea,
    ProyeccionArea,
    RegistroHistoricoError,
)
from proyecciones.tests_revision import MOTIVO, BaseRevision


class BaseAprobacion(BaseRevision):
    def setUp(self):
        super().setUp()
        self.url_aprobar = reverse("proyecciones:revision_aprobar", args=[self.proyeccion.pk])
        self.url_ajustar = reverse("proyecciones:revision_ajustar_linea", args=[self.proyeccion.pk, self.linea.pk])

    def datos_aprobacion(self, accion="aprobar", motivo=MOTIVO, **cantidades):
        datos = {"accion": accion, "motivo": motivo}
        for linea in (self.linea, self.linea_dos):
            datos[f"autorizada_{linea.pk}"] = ""
        datos.update(cantidades)
        return datos

    def aprobar(self, actor=None):
        return servicios.aprobar_proyeccion(self.proyeccion, actor=actor or self.administrador, motivo=MOTIVO)

    def exigir_requeridas(self, valor):
        Parametro.objects.filter(clave=APROBACIONES_REQUERIDAS).update(valor=str(valor))


class AprobacionTests(BaseAprobacion):
    def test_aprobar_guarda_quien_y_cuando_y_autoriza_el_total_anual_por_defecto(self):
        self.client.force_login(self.administrador)
        antes = timezone.now()
        respuesta = self.client.post(self.url_aprobar, self.datos_aprobacion())
        self.assertRedirects(respuesta, self.url_detalle)
        self.proyeccion.refresh_from_db()
        self.assertEqual(self.proyeccion.estado, ProyeccionArea.Estado.APROBADA)
        self.assertEqual(self.proyeccion.aprobado_por, self.administrador)
        self.assertGreaterEqual(self.proyeccion.fecha_aprobacion, antes)
        self.linea.refresh_from_db()
        self.linea_dos.refresh_from_db()
        self.assertEqual(self.linea.cantidad_autorizada, 5)
        self.assertEqual(self.linea_dos.cantidad_autorizada, 10)
        aprobacion = AprobacionProyeccion.objects.get()
        self.assertEqual(aprobacion.usuario, self.administrador)
        self.assertEqual(aprobacion.fecha_envio_aprobada, self.proyeccion.fecha_envio)
        registro = RegistroBitacora.objects.get(accion="proyeccion_area.aprobada")
        self.assertEqual(registro.valor_anterior["estado"], "enviada")
        self.assertEqual(registro.valor_nuevo["estado"], "aprobada")
        self.assertEqual(registro.valor_nuevo["aprobado_por"]["id"], self.administrador.pk)
        self.assertEqual(registro.motivo, MOTIVO)

    def test_formulario_propone_el_total_anual(self):
        self.client.force_login(self.administrador)
        respuesta = self.client.get(self.url_detalle)
        formulario = respuesta.context["formulario_autorizacion"]
        self.assertEqual(formulario.fields[f"autorizada_{self.linea.pk}"].initial, 5)
        self.assertEqual(formulario.fields[f"autorizada_{self.linea_dos.pk}"].initial, 10)

    def test_aprobar_con_cantidad_autorizada_distinta_queda_en_bitacora(self):
        self.client.force_login(self.administrador)
        self.client.post(self.url_aprobar, self.datos_aprobacion(**{f"autorizada_{self.linea.pk}": "4"}))
        self.linea.refresh_from_db()
        self.assertEqual(self.linea.cantidad_autorizada, 4)
        registro = RegistroBitacora.objects.get(accion="linea.cantidad_autorizada", objeto_id=str(self.linea.pk))
        self.assertEqual(registro.valor_anterior, {"cantidad_autorizada": None})
        self.assertEqual(registro.valor_nuevo, {"cantidad_autorizada": 4})

    def test_guardar_cantidades_no_aprueba(self):
        self.client.force_login(self.administrador)
        self.client.post(
            self.url_aprobar, self.datos_aprobacion(accion="guardar", **{f"autorizada_{self.linea.pk}": "3"})
        )
        self.proyeccion.refresh_from_db()
        self.linea.refresh_from_db()
        self.assertEqual(self.proyeccion.estado, ProyeccionArea.Estado.ENVIADA)
        self.assertEqual(self.linea.cantidad_autorizada, 3)
        self.assertFalse(AprobacionProyeccion.objects.exists())

    def test_aprobar_sin_motivo_o_con_cantidad_invalida_se_rechaza(self):
        self.client.force_login(self.administrador)
        for datos in (
            self.datos_aprobacion(motivo=""),
            self.datos_aprobacion(**{f"autorizada_{self.linea.pk}": "-1"}),
            self.datos_aprobacion(**{f"autorizada_{self.linea.pk}": "1.5"}),
        ):
            with self.subTest(datos=datos):
                respuesta = self.client.post(self.url_aprobar, datos)
                self.assertEqual(respuesta.status_code, 200)
                self.assertTrue(respuesta.context["formulario_autorizacion"].errors)
        self.proyeccion.refresh_from_db()
        self.assertEqual(self.proyeccion.estado, ProyeccionArea.Estado.ENVIADA)
        self.assertFalse(AprobacionProyeccion.objects.exists())

    def test_solo_se_aprueba_una_proyeccion_enviada(self):
        with self.assertRaises(ValidationError):
            servicios.aprobar_proyeccion(self.otra_proyeccion, actor=self.administrador, motivo=MOTIVO)
        self.client.force_login(self.administrador)
        url = reverse("proyecciones:revision_aprobar", args=[self.otra_proyeccion.pk])
        self.client.post(url, {"accion": "aprobar", "motivo": MOTIVO})
        self.otra_proyeccion.refresh_from_db()
        self.assertEqual(self.otra_proyeccion.estado, ProyeccionArea.Estado.BORRADOR)

    def test_servicio_exige_rol_de_administracion(self):
        for usuario in (self.coordinador, self.proveedor):
            with self.subTest(rol=usuario.rol), self.assertRaises(PermissionDenied):
                self.aprobar(usuario)
        self.proyeccion.refresh_from_db()
        self.assertEqual(self.proyeccion.estado, ProyeccionArea.Estado.ENVIADA)


class BloqueoPorAprobacionTests(BaseAprobacion):
    def setUp(self):
        super().setUp()
        self.aprobar()
        self.proyeccion.refresh_from_db()
        self.linea.refresh_from_db()

    def test_coordinador_no_puede_editar(self):
        self.client.force_login(self.coordinador)
        url = reverse("proyecciones:mi_proyeccion_detalle", args=[self.proyeccion.pk])
        respuesta = self.client.get(url)
        self.assertFalse(respuesta.context["editable"])
        self.assertContains(respuesta, "La proyección fue aprobada")
        datos = {
            "lineas-TOTAL_FORMS": "1",
            "lineas-INITIAL_FORMS": "1",
            "lineas-MIN_NUM_FORMS": "0",
            "lineas-MAX_NUM_FORMS": "1000",
            "lineas-0-id": str(self.linea.pk),
            "lineas-0-producto_servicio": "Guantes de examen",
            "lineas-0-unidad": str(self.unidad.pk),
            "lineas-0-precio_estimado": "99.00",
            "motivo": "Intento ficticio",
            "accion": "guardar",
        }
        for campo in CAMPOS_CANTIDADES_MENSUALES:
            datos[f"lineas-0-{campo}"] = "1"
        self.client.post(url, datos)
        self.linea.refresh_from_db()
        self.assertEqual(self.linea.precio_estimado, Decimal("12.50"))

    def test_administracion_no_puede_corregir_devolver_ni_reaprobar(self):
        self.client.force_login(self.administrador)
        respuesta = self.client.post(self.url_corregir, self.datos_correccion(cantidad_enero="9"))
        self.assertRedirects(respuesta, self.url_detalle, fetch_redirect_response=False)
        self.client.post(self.url_devolver, {"motivo": MOTIVO})
        self.client.post(self.url_aprobar, self.datos_aprobacion(accion="guardar", **{f"autorizada_{self.linea.pk}": "1"}))
        self.proyeccion.refresh_from_db()
        self.linea.refresh_from_db()
        self.assertEqual(self.proyeccion.estado, ProyeccionArea.Estado.APROBADA)
        self.assertEqual(self.linea.cantidad_enero, 2)
        self.assertEqual(self.linea.cantidad_autorizada, 5)

    def test_servicios_ordinarios_rechazan_cualquier_rol(self):
        self.linea.cantidad_enero = 9
        nueva = Linea(proyeccion=self.proyeccion, producto_servicio="Nueva", unidad=self.unidad, precio_estimado=1)
        intentos = [
            lambda: servicios.guardar_linea(self.linea, actor=self.administrador, motivo=MOTIVO),
            lambda: servicios.guardar_linea(nueva, actor=self.desarrollador, motivo=MOTIVO),
            lambda: servicios.eliminar_linea(self.linea, actor=self.administrador, motivo=MOTIVO),
            lambda: servicios.guardar_proyeccion_area(self.proyeccion, actor=self.administrador, motivo=MOTIVO),
            lambda: servicios.corregir_linea(self.linea, actor=self.administrador, motivo=MOTIVO),
            lambda: servicios.devolver_proyeccion(self.proyeccion, actor=self.administrador, motivo=MOTIVO),
            lambda: servicios.guardar_cantidades_autorizadas(
                self.proyeccion, {self.linea.pk: 1}, actor=self.administrador, motivo=MOTIVO
            ),
            lambda: self.aprobar(self.desarrollador),
        ]
        for numero, intento in enumerate(intentos):
            with self.subTest(intento=numero), self.assertRaises(ValidationError):
                intento()
        self.linea.refresh_from_db()
        self.assertEqual(self.linea.cantidad_enero, 2)
        self.assertEqual(Linea.objects.filter(proyeccion=self.proyeccion).count(), 2)

    def test_aprobacion_es_historica(self):
        aprobacion = AprobacionProyeccion.objects.get()
        with self.assertRaises(RegistroHistoricoError):
            aprobacion.save()
        with self.assertRaises(RegistroHistoricoError):
            aprobacion.delete()
        with self.assertRaises(RegistroHistoricoError):
            AprobacionProyeccion.objects.all().update(motivo="alterado")
        with self.assertRaises(RegistroHistoricoError):
            AprobacionProyeccion.objects.all().delete()


class VariasAprobacionesTests(BaseAprobacion):
    def test_por_defecto_basta_una_aprobacion(self):
        self.assertEqual(servicios.aprobaciones_requeridas(), 1)
        _, aprobada = self.aprobar()
        self.assertTrue(aprobada)

    def test_con_dos_requeridas_hacen_falta_dos_administradores_distintos(self):
        self.exigir_requeridas(2)
        _, aprobada = self.aprobar()
        self.assertFalse(aprobada)
        self.proyeccion.refresh_from_db()
        self.assertEqual(self.proyeccion.estado, ProyeccionArea.Estado.ENVIADA)
        self.assertIsNone(self.proyeccion.fecha_aprobacion)
        with self.assertRaises(ValidationError):
            self.aprobar()  # El mismo administrador no cuenta dos veces.
        _, aprobada = self.aprobar(self.desarrollador)
        self.assertTrue(aprobada)
        self.proyeccion.refresh_from_db()
        self.assertEqual(self.proyeccion.aprobado_por, self.desarrollador)
        self.assertEqual(AprobacionProyeccion.objects.count(), 2)

    def test_devolver_anula_las_aprobaciones_parciales_sin_borrarlas(self):
        self.exigir_requeridas(2)
        self.aprobar()
        servicios.devolver_proyeccion(self.proyeccion, actor=self.desarrollador, motivo="Devolución ficticia")
        ProyeccionArea.objects.filter(pk=self.proyeccion.pk).update(
            estado=ProyeccionArea.Estado.ENVIADA,
            fecha_envio=timezone.now() + timedelta(minutes=1),
            enviado_por=self.coordinador,
        )
        self.proyeccion.refresh_from_db()
        self.assertEqual(servicios.aprobaciones_vigentes(self.proyeccion).count(), 0)
        self.assertEqual(AprobacionProyeccion.objects.count(), 1)
        _, aprobada = self.aprobar()  # El mismo administrador puede aprobar el nuevo envío.
        self.assertFalse(aprobada)
        self.assertEqual(servicios.aprobaciones_vigentes(self.proyeccion).count(), 1)

    def test_parametro_no_admite_menos_de_una_aprobacion(self):
        from parametros.servicios import cambiar_valor

        parametro = Parametro.objects.get(clave=APROBACIONES_REQUERIDAS)
        with self.assertRaises(ValidationError):
            cambiar_valor(parametro, "0", actor=self.administrador, motivo=MOTIVO)


class AjusteTests(BaseAprobacion):
    def setUp(self):
        super().setUp()
        self.aprobar()
        self.linea.refresh_from_db()

    def ajustar(self, campo, valor, justificacion="Cambio de proveedor (ficticio)", linea=None):
        return servicios.registrar_ajuste(
            linea or self.linea, campo, valor, actor=self.administrador, justificacion=justificacion
        )

    def test_ajuste_sin_justificacion_se_rechaza(self):
        with self.assertRaises(ValidationError) as contexto:
            self.ajustar("precio_estimado", "13.00", justificacion="   ")
        self.assertIn("justificacion", contexto.exception.message_dict)
        self.client.force_login(self.administrador)
        respuesta = self.client.post(
            self.url_ajustar, {"campo": "precio_estimado", "valor_nuevo": "13.00", "justificacion": ""}
        )
        self.assertEqual(respuesta.status_code, 200)
        self.assertTrue(respuesta.context["formulario"].errors["justificacion"])
        self.assertFalse(Ajuste.objects.exists())

    def test_el_valor_aprobado_no_cambia_y_se_muestra_el_vigente(self):
        self.ajustar("precio_estimado", "13.00")
        self.ajustar("precio_estimado", "14.00", justificacion="Segundo ajuste ficticio")
        self.linea.refresh_from_db()
        self.assertEqual(self.linea.precio_estimado, Decimal("12.50"))
        primero, segundo = Ajuste.objects.order_by("id")
        self.assertEqual(primero.valor_aprobado, "12.50")
        self.assertEqual(primero.valor_anterior, "12.50")
        self.assertEqual(primero.valor_nuevo, "13.00")
        self.assertEqual(segundo.valor_aprobado, "12.50")
        self.assertEqual(segundo.valor_anterior, "13.00")
        self.assertEqual(segundo.valor_nuevo, "14.00")
        self.assertEqual(servicios.valores_vigentes(self.linea)["precio_estimado"], Decimal("14.00"))
        linea = servicios.anotar_vigentes([Linea.objects.prefetch_related("ajustes").get(pk=self.linea.pk)])[0]
        self.assertEqual(linea.costo_vigente, Decimal("70.00"))
        self.assertEqual(linea.costo_anual, Decimal("62.50"))

        self.client.force_login(self.administrador)
        respuesta = self.client.get(self.url_detalle)
        self.assertContains(respuesta, "Aprobado: 12,50")
        self.assertContains(respuesta, "14,00")
        self.assertContains(respuesta, "Segundo ajuste ficticio")

    def test_ajuste_desde_la_vista_registra_autor_y_bitacora(self):
        self.client.force_login(self.administrador)
        respuesta = self.client.post(
            self.url_ajustar,
            {"campo": "cantidad_autorizada", "valor_nuevo": "3", "justificacion": "Recorte presupuestal ficticio"},
        )
        self.assertRedirects(respuesta, self.url_detalle)
        ajuste = Ajuste.objects.get()
        self.assertEqual(ajuste.usuario, self.administrador)
        self.assertEqual((ajuste.valor_aprobado, ajuste.valor_anterior, ajuste.valor_nuevo), (5, 5, 3))
        self.linea.refresh_from_db()
        self.assertEqual(self.linea.cantidad_autorizada, 5)
        registro = RegistroBitacora.objects.get(accion="linea.ajustada")
        self.assertEqual(registro.actor, self.administrador)
        self.assertEqual(registro.valor_anterior, {"cantidad_autorizada": 5})
        self.assertEqual(registro.valor_nuevo, {"cantidad_autorizada": 3})
        self.assertEqual(registro.motivo, "Recorte presupuestal ficticio")

        self.client.force_login(self.coordinador)
        respuesta = self.client.get(reverse("proyecciones:mi_proyeccion_detalle", args=[self.proyeccion.pk]))
        linea = next(l for l in respuesta.context["lineas_lectura"] if l.pk == self.linea.pk)
        self.assertEqual(linea.vigente["cantidad_autorizada"], 3)
        self.assertContains(respuesta, "Ajustada")

    def test_valores_y_campos_invalidos_se_rechazan(self):
        casos = [
            ("cantidad_enero", "-1"),
            ("cantidad_enero", "1.5"),
            ("cantidad_autorizada", ""),
            ("precio_estimado", "12.345"),
            ("precio_estimado", "-1"),
            ("precio_estimado", "12.50"),  # igual al vigente
            ("producto_servicio", "Otro"),
            ("unidad", str(self.otra_unidad.pk)),
        ]
        for campo, valor in casos:
            with self.subTest(campo=campo, valor=valor), self.assertRaises(ValidationError):
                self.ajustar(campo, valor)
        self.assertFalse(Ajuste.objects.exists())

    def test_solo_se_ajusta_una_proyeccion_aprobada(self):
        with self.assertRaises(ValidationError):
            self.ajustar("precio_estimado", "2.00", linea=self.linea_ajena)
        self.client.force_login(self.administrador)
        url = reverse("proyecciones:revision_ajustar_linea", args=[self.otra_proyeccion.pk, self.linea_ajena.pk])
        self.assertRedirects(
            self.client.get(url), reverse("proyecciones:revision_detalle", args=[self.otra_proyeccion.pk])
        )

    def test_linea_de_otra_proyeccion_por_url_da_404(self):
        self.client.force_login(self.administrador)
        url = reverse("proyecciones:revision_ajustar_linea", args=[self.proyeccion.pk, self.linea_ajena.pk])
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_servicio_exige_rol_de_administracion(self):
        with self.assertRaises(PermissionDenied):
            servicios.registrar_ajuste(
                self.linea, "precio_estimado", "13.00", actor=self.coordinador, justificacion="Ficticia"
            )
        self.assertFalse(Ajuste.objects.exists())

    def test_ajuste_es_historico(self):
        ajuste = self.ajustar("cantidad_marzo", "4")
        for intento in (
            ajuste.save,
            ajuste.delete,
            lambda: Ajuste.objects.update(justificacion="alterada"),
            lambda: Ajuste.objects.all().delete(),
        ):
            with self.assertRaises(RegistroHistoricoError):
                intento()


class PermisosAprobacionTests(BaseAprobacion):
    def test_coordinador_y_proveedor_reciben_403(self):
        for usuario in (self.coordinador, self.proveedor):
            self.client.force_login(usuario)
            for url in (self.url_aprobar, self.url_ajustar):
                with self.subTest(rol=usuario.rol, url=url):
                    self.assertEqual(self.client.get(url).status_code, 403)
                    datos = {**self.datos_aprobacion(), "campo": "precio_estimado", "valor_nuevo": "1", "justificacion": "x"}
                    self.assertEqual(self.client.post(url, datos).status_code, 403)
        self.proyeccion.refresh_from_db()
        self.assertEqual(self.proyeccion.estado, ProyeccionArea.Estado.ENVIADA)
        self.assertFalse(AprobacionProyeccion.objects.exists())
        self.assertFalse(Ajuste.objects.exists())

    def test_sin_sesion_redirige_al_ingreso(self):
        for url in (self.url_aprobar, self.url_ajustar):
            with self.subTest(url=url):
                respuesta = self.client.post(url, self.datos_aprobacion())
                self.assertEqual(respuesta.status_code, 302)
                self.assertTrue(respuesta["Location"].startswith(reverse("cuentas:ingresar")))
        self.assertFalse(AprobacionProyeccion.objects.exists())

    def test_administracion_entra_y_aprobar_solo_acepta_post(self):
        self.aprobar()
        for usuario in (self.administrador, self.desarrollador):
            self.client.force_login(usuario)
            with self.subTest(rol=usuario.rol):
                self.assertEqual(self.client.get(self.url_ajustar).status_code, 200)
                self.assertEqual(self.client.get(self.url_aprobar).status_code, 405)
                self.assertEqual(self.client.get(self.url_detalle).status_code, 200)
