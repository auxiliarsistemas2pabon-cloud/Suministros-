from datetime import date, timedelta

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from bitacora.models import RegistroBitacora
from cuentas.models import Rol, Usuario
from cuentas.tests.utilidades import crear_usuario
from parametros import servicios as servicios_parametros
from parametros.catalogo import DIAS_ALERTA_VENCIMIENTO, ROLES_APROBADORES_PROVEEDOR
from parametros.models import Parametro
from proveedores import servicios
from proveedores.models import CategoriaProveedor, DocumentoProveedor, Proveedor, TipoDocumento
from proveedores.tests.utilidades import (
    MOTIVO,
    categoria,
    crear_documento_con_enlace,
    crear_proveedor,
    tipo_documento,
)


class FichaProveedorTests(TestCase):
    def setUp(self):
        self.administrador = crear_usuario(Rol.ADMINISTRADOR, correo="admin@ejemplo.test")
        self.client.force_login(self.administrador)

    def datos(self, **cambios):
        datos = {
            "nit": "900.123.456-8",
            "razon_social": "  Droguería   Ficticia S.A.S. ",
            "tipo_persona": Proveedor.TipoPersona.JURIDICA,
            "contacto_nombre": "Ana Ficticia",
            "contacto_correo": "Ana.Ficticia@Ejemplo.test",
            "contacto_telefono": "+57 601 555 0101",
            "direccion": "Carrera Ficticia 10 # 20-30",
            "categoria": categoria().pk,
            "motivo": MOTIVO,
        }
        datos.update(cambios)
        return datos

    def test_crear_desde_la_vista_registra_en_la_bitacora(self):
        respuesta = self.client.post(reverse("proveedores:nuevo"), self.datos())
        proveedor = Proveedor.objects.get()
        self.assertRedirects(respuesta, reverse("proveedores:detalle", args=[proveedor.pk]))
        self.assertEqual(proveedor.razon_social, "Droguería Ficticia S.A.S.")
        self.assertEqual(proveedor.contacto_correo, "ana.ficticia@ejemplo.test")
        self.assertEqual(proveedor.estado, Proveedor.Estado.REGISTRADO)
        registro = RegistroBitacora.objects.get(accion="proveedor.creado")
        self.assertEqual(registro.actor, self.administrador)
        self.assertEqual(registro.valor_nuevo["nit"], "900123456")
        self.assertEqual(registro.valor_nuevo["digito_verificacion"], 8)
        self.assertEqual(registro.motivo, MOTIVO)

    def test_validaciones_del_formulario(self):
        url = reverse("proveedores:nuevo")
        self.assertContains(self.client.post(url, self.datos(motivo="")), "Indique el motivo")
        self.assertContains(self.client.post(url, self.datos(nit="900.123.456-1")), "debería ser 8")
        self.assertContains(self.client.post(url, self.datos(contacto_telefono="abc")), "teléfono válido")
        respuesta = self.client.post(url, self.datos(contacto_correo="no-es-correo"))
        self.assertIn("contacto_correo", respuesta.context["formulario"].errors)
        self.assertFalse(Proveedor.objects.exists())

    def test_categoria_inactiva_no_se_puede_elegir_pero_se_conserva(self):
        inactiva = CategoriaProveedor.objects.create(nombre="Categoría Retirada", activo=False)
        respuesta = self.client.post(reverse("proveedores:nuevo"), self.datos(categoria=inactiva.pk))
        self.assertEqual(respuesta.status_code, 200)
        self.assertFalse(Proveedor.objects.exists())
        proveedor = crear_proveedor(categoria=categoria("Activa por ahora"))
        CategoriaProveedor.objects.filter(pk=proveedor.categoria_id).update(activo=False)
        proveedor.refresh_from_db()
        proveedor.razon_social = "Cambio de nombre ficticio"
        servicios.guardar_proveedor(proveedor, actor=self.administrador, motivo=MOTIVO)

    def test_editar_no_cambia_el_estado(self):
        proveedor = crear_proveedor()
        Proveedor.objects.filter(pk=proveedor.pk).update(estado=Proveedor.Estado.APROBADO)
        proveedor.refresh_from_db()
        proveedor.estado = Proveedor.Estado.INACTIVO
        proveedor.razon_social = "Otro nombre ficticio"
        servicios.guardar_proveedor(proveedor, actor=self.administrador, motivo=MOTIVO)
        proveedor.refresh_from_db()
        self.assertEqual(proveedor.estado, Proveedor.Estado.APROBADO)

    def test_no_hay_vista_ni_permiso_para_borrar_proveedores(self):
        proveedor = crear_proveedor()
        crear_documento_con_enlace(proveedor, self.administrador)
        from django.db.models import ProtectedError

        with self.assertRaises(ProtectedError):
            proveedor.delete()


class EstadoProveedorTests(TestCase):
    def setUp(self):
        self.administrador = crear_usuario(Rol.ADMINISTRADOR, correo="admin@ejemplo.test")
        self.desarrollador = crear_usuario(Rol.DESARROLLADOR, correo="dev@ejemplo.test")
        self.proveedor = crear_proveedor()

    def _cambiar_parametro(self, clave, valor):
        parametro = Parametro.objects.get(clave=clave)
        servicios_parametros.cambiar_valor(parametro, valor, actor=self.desarrollador, motivo=MOTIVO)

    def test_cambiar_estado_con_motivo_y_bitacora(self):
        servicios.cambiar_estado(self.proveedor, Proveedor.Estado.EN_REVISION, actor=self.administrador, motivo=MOTIVO)
        servicios.cambiar_estado(self.proveedor, Proveedor.Estado.APROBADO, actor=self.administrador, motivo=MOTIVO)
        self.proveedor.refresh_from_db()
        self.assertEqual(self.proveedor.estado, Proveedor.Estado.APROBADO)
        registro = RegistroBitacora.objects.filter(accion="proveedor.estado_cambiado").first()
        self.assertEqual(registro.valor_anterior, {"estado": "en_revision"})
        self.assertEqual(registro.valor_nuevo, {"estado": "aprobado"})

    def test_sin_motivo_o_al_mismo_estado_se_rechaza(self):
        with self.assertRaises(ValidationError):
            servicios.cambiar_estado(self.proveedor, Proveedor.Estado.APROBADO, actor=self.administrador, motivo=" ")
        with self.assertRaises(ValidationError):
            servicios.cambiar_estado(self.proveedor, Proveedor.Estado.REGISTRADO, actor=self.administrador, motivo=MOTIVO)
        with self.assertRaises(ValidationError):
            servicios.cambiar_estado(self.proveedor, "borrado", actor=self.administrador, motivo=MOTIVO)

    def test_d03_por_defecto_aprueban_administrador_y_desarrollador(self):
        self.assertEqual(servicios.roles_aprobadores(), ["administrador", "desarrollador"])
        self.assertTrue(servicios.puede_aprobar(self.administrador))

    def test_d03_restringido_a_desarrollador(self):
        self._cambiar_parametro(ROLES_APROBADORES_PROVEEDOR, "desarrollador")
        with self.assertRaises(PermissionDenied):
            servicios.cambiar_estado(self.proveedor, Proveedor.Estado.APROBADO, actor=self.administrador, motivo=MOTIVO)
        # El administrador sí puede pasar a otros estados, y no ve la opción de aprobar.
        servicios.cambiar_estado(self.proveedor, Proveedor.Estado.EN_REVISION, actor=self.administrador, motivo=MOTIVO)
        self.assertNotIn("aprobado", dict(servicios.estados_posibles(self.proveedor, self.administrador)))
        self.client.force_login(self.administrador)
        url = reverse("proveedores:estado", args=[self.proveedor.pk])
        respuesta = self.client.post(url, {"estado": "aprobado", "motivo": MOTIVO})
        self.assertEqual(respuesta.status_code, 200)
        self.proveedor.refresh_from_db()
        self.assertEqual(self.proveedor.estado, Proveedor.Estado.EN_REVISION)
        servicios.cambiar_estado(self.proveedor, Proveedor.Estado.APROBADO, actor=self.desarrollador, motivo=MOTIVO)

    def test_parametro_d03_solo_acepta_roles_de_administracion(self):
        parametro = Parametro.objects.get(clave=ROLES_APROBADORES_PROVEEDOR)
        for valor in ("", "coordinador", "administrador, proveedor", "jefe"):
            with self.subTest(valor=valor), self.assertRaises(ValidationError):
                servicios_parametros.cambiar_valor(parametro, valor, actor=self.desarrollador, motivo=MOTIVO)
        servicios_parametros.cambiar_valor(parametro, " Desarrollador , administrador ", actor=self.desarrollador, motivo=MOTIVO)
        parametro.refresh_from_db()
        self.assertEqual(parametro.valor, "desarrollador,administrador")

    def test_vista_cambiar_estado(self):
        self.client.force_login(self.administrador)
        url = reverse("proveedores:estado", args=[self.proveedor.pk])
        self.assertContains(self.client.post(url, {"estado": "inactivo", "motivo": ""}), "Indique el motivo")
        respuesta = self.client.post(url, {"estado": "inactivo", "motivo": MOTIVO})
        self.assertRedirects(respuesta, reverse("proveedores:detalle", args=[self.proveedor.pk]))
        self.proveedor.refresh_from_db()
        self.assertFalse(self.proveedor.activo)


class DocumentoReglasTests(TestCase):
    def setUp(self):
        self.administrador = crear_usuario(Rol.ADMINISTRADOR, correo="admin@ejemplo.test")
        self.proveedor = crear_proveedor()
        self.hoy = timezone.localdate()

    def _documento(self, **campos):
        datos = {
            "proveedor": self.proveedor,
            "tipo": tipo_documento(),
            "fecha_expedicion": self.hoy - timedelta(days=5),
            "fecha_vencimiento": self.hoy + timedelta(days=100),
            "enlace": "https://documentos.ejemplo.test/x",
        }
        datos.update(campos)
        return DocumentoProveedor(**datos)

    def _guardar(self, documento):
        return servicios.guardar_documento(documento, actor=self.administrador, motivo=MOTIVO)

    def test_vencimiento_obligatorio_si_el_tipo_lo_requiere(self):
        with self.assertRaises(ValidationError) as contexto:
            self._guardar(self._documento(fecha_vencimiento=None))
        self.assertIn("fecha_vencimiento", contexto.exception.message_dict)
        rut = tipo_documento("RUT", requiere_vencimiento=False)
        self._guardar(self._documento(tipo=rut, fecha_vencimiento=None))

    def test_fechas_coherentes(self):
        with self.assertRaises(ValidationError):
            self._guardar(self._documento(fecha_vencimiento=self.hoy - timedelta(days=10)))
        with self.assertRaises(ValidationError):
            self._guardar(self._documento(fecha_expedicion=self.hoy + timedelta(days=1)))
        documento = self._guardar(self._documento())
        with self.assertRaises(IntegrityError), transaction.atomic():
            DocumentoProveedor.objects.filter(pk=documento.pk).update(fecha_vencimiento=date(2000, 1, 1))

    def test_enlace_solo_http_o_https(self):
        with self.assertRaises(ValidationError) as contexto:
            self._guardar(self._documento(enlace="javascript:alert(1)"))
        self.assertIn("enlace", contexto.exception.message_dict)
        with self.assertRaises(ValidationError):
            self._guardar(self._documento(enlace="ftp://documentos.ejemplo.test/x"))

    def test_tipo_inactivo_no_se_puede_elegir(self):
        inactivo = TipoDocumento.objects.create(nombre="Tipo Retirado", activo=False)
        with self.assertRaises(ValidationError) as contexto:
            self._guardar(self._documento(tipo=inactivo))
        self.assertIn("tipo", contexto.exception.message_dict)

    def test_editar_registra_solo_lo_que_cambio_y_sin_cambios_se_rechaza(self):
        documento = self._guardar(self._documento())
        documento = DocumentoProveedor.objects.get(pk=documento.pk)
        documento.fecha_vencimiento = self.hoy + timedelta(days=400)
        self._guardar(documento)
        registro = RegistroBitacora.objects.get(accion="documento_proveedor.modificado")
        self.assertEqual(set(registro.valor_nuevo), {"fecha_vencimiento"})
        with self.assertRaisesMessage(ValidationError, "No hay cambios"):
            self._guardar(DocumentoProveedor.objects.get(pk=documento.pk))

    def test_no_se_puede_pasar_a_otro_proveedor(self):
        documento = self._guardar(self._documento())
        documento.proveedor = crear_proveedor(razon_social="Otro Ficticio")
        with self.assertRaises(ValidationError):
            self._guardar(documento)

    def test_eliminar_exige_motivo_y_deja_la_bitacora(self):
        documento = self._guardar(self._documento())
        with self.assertRaises(ValidationError):
            servicios.eliminar_documento(documento, actor=self.administrador, motivo="")
        servicios.eliminar_documento(documento, actor=self.administrador, motivo=MOTIVO)
        registro = RegistroBitacora.objects.get(accion="documento_proveedor.eliminado")
        self.assertEqual(registro.valor_anterior["enlace"], "https://documentos.ejemplo.test/x")
        self.assertEqual(registro.motivo, MOTIVO)


class VencimientosTests(TestCase):
    def setUp(self):
        self.administrador = crear_usuario(Rol.ADMINISTRADOR, correo="admin@ejemplo.test")
        self.proveedor = crear_proveedor(razon_social="Proveedor Con Alertas")
        self.hoy = timezone.localdate()

    def test_clasificacion_de_vigencia(self):
        hoy = date(2026, 11, 9)
        self.assertEqual(servicios.vigencia(None, hoy, 30), servicios.VIGENCIA_SIN_VENCIMIENTO)
        self.assertEqual(servicios.vigencia(hoy - timedelta(days=1), hoy, 30), servicios.VIGENCIA_VENCIDO)
        self.assertEqual(servicios.vigencia(hoy, hoy, 30), servicios.VIGENCIA_POR_VENCER)
        self.assertEqual(servicios.vigencia(hoy + timedelta(days=30), hoy, 30), servicios.VIGENCIA_POR_VENCER)
        self.assertEqual(servicios.vigencia(hoy + timedelta(days=31), hoy, 30), servicios.VIGENCIA_VIGENTE)

    def test_alertas_de_vencidos_y_por_vencer(self):
        vencido = crear_documento_con_enlace(self.proveedor, self.administrador, tipo=tipo_documento("Póliza"), vence_en_dias=-3)
        por_vencer = crear_documento_con_enlace(self.proveedor, self.administrador, vence_en_dias=15)
        crear_documento_con_enlace(self.proveedor, self.administrador, tipo=tipo_documento("Registro sanitario"), vence_en_dias=90)
        crear_documento_con_enlace(self.proveedor, self.administrador, tipo=tipo_documento("RUT", False))
        alertas = {d.pk: d.vigencia for d in servicios.alertas_vencimiento()}
        self.assertEqual(alertas, {vencido.pk: "vencido", por_vencer.pk: "por_vencer"})
        self.assertEqual(servicios.resumen_alertas(), {"vencidos": 1, "por_vencer": 1, "dias": 30})

    def test_un_documento_renovado_ya_no_alerta(self):
        tipo = tipo_documento()
        crear_documento_con_enlace(self.proveedor, self.administrador, tipo=tipo, vence_en_dias=-10, expedido_hace_dias=400)
        nuevo = crear_documento_con_enlace(self.proveedor, self.administrador, tipo=tipo, vence_en_dias=300, expedido_hace_dias=2)
        self.assertEqual(servicios.alertas_vencimiento(), [])
        self.assertEqual(list(servicios.documentos_actuales()), [nuevo])

    def test_proveedores_inactivos_no_alertan(self):
        crear_documento_con_enlace(self.proveedor, self.administrador, vence_en_dias=-1)
        Proveedor.objects.filter(pk=self.proveedor.pk).update(estado=Proveedor.Estado.INACTIVO)
        self.assertEqual(servicios.alertas_vencimiento(), [])

    def test_los_dias_de_aviso_son_un_parametro(self):
        crear_documento_con_enlace(self.proveedor, self.administrador, vence_en_dias=45)
        self.assertEqual(servicios.alertas_vencimiento(), [])
        parametro = Parametro.objects.get(clave=DIAS_ALERTA_VENCIMIENTO)
        servicios_parametros.cambiar_valor(parametro, 60, actor=self.administrador, motivo=MOTIVO)
        self.assertEqual(len(servicios.alertas_vencimiento()), 1)
        with self.assertRaises(ValidationError):
            servicios_parametros.cambiar_valor(parametro, 0, actor=self.administrador, motivo=MOTIVO)

    def test_rojo_solo_para_vencidos_en_pantalla(self):
        crear_documento_con_enlace(self.proveedor, self.administrador, tipo=tipo_documento("Póliza"), vence_en_dias=-3)
        crear_documento_con_enlace(self.proveedor, self.administrador, vence_en_dias=10)
        self.client.force_login(self.administrador)
        respuesta = self.client.get(reverse("proveedores:vencimientos"))
        self.assertContains(respuesta, "vigencia--vencido", count=1)
        self.assertContains(respuesta, "vigencia--por-vencer", count=1)
        lista = self.client.get(reverse("proveedores:lista"))
        self.assertContains(lista, "Hay 1 documento vencido")
        self.assertContains(lista, "1 documento vence en los próximos 30 días")
        ficha = self.client.get(reverse("proveedores:detalle", args=[self.proveedor.pk]))
        self.assertContains(ficha, 'class="mensaje mensaje--error"', count=1)
        self.assertContains(ficha, "Póliza")

    def test_sin_vencidos_no_hay_alerta_roja(self):
        crear_documento_con_enlace(self.proveedor, self.administrador, vence_en_dias=10)
        self.client.force_login(self.administrador)
        for url in (reverse("proveedores:lista"), reverse("proveedores:vencimientos"), reverse("proveedores:detalle", args=[self.proveedor.pk])):
            with self.subTest(url=url):
                respuesta = self.client.get(url)
                self.assertNotContains(respuesta, "mensaje--error")
                self.assertNotContains(respuesta, "vigencia--vencido")


class UsuarioProveedorTests(TestCase):
    """Usuario.proveedor: obligatorio para el rol proveedor, prohibido para los demás."""

    def setUp(self):
        self.proveedor = crear_proveedor()

    def test_rol_proveedor_exige_ficha(self):
        with self.assertRaises(ValidationError) as contexto:
            Usuario.objects.create_user(
                correo="sin.ficha@ejemplo.test", password="x", nombre="Sin Ficha", rol=Rol.PROVEEDOR
            )
        self.assertIn("proveedor", contexto.exception.message_dict)
        usuario = crear_usuario(Rol.PROVEEDOR, correo="con.ficha@ejemplo.test", proveedor=self.proveedor)
        self.assertEqual(usuario.proveedor, self.proveedor)
        self.assertEqual(list(self.proveedor.usuarios.all()), [usuario])

    def test_otros_roles_no_pueden_tener_ficha(self):
        for rol in (Rol.ADMINISTRADOR, Rol.DESARROLLADOR, Rol.COORDINADOR):
            with self.subTest(rol=rol), self.assertRaises(ValidationError) as contexto:
                crear_usuario(rol, correo=f"{rol}@ejemplo.test", proveedor=self.proveedor)
            self.assertIn("proveedor", contexto.exception.message_dict)

    def test_la_base_tambien_lo_impide(self):
        usuario = crear_usuario(Rol.PROVEEDOR, proveedor=self.proveedor)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Usuario.objects.filter(pk=usuario.pk).update(proveedor=None)
        administrador = crear_usuario(Rol.ADMINISTRADOR, correo="admin@ejemplo.test")
        with self.assertRaises(IntegrityError), transaction.atomic():
            Usuario.objects.filter(pk=administrador.pk).update(proveedor=self.proveedor)

    def test_no_se_asigna_un_proveedor_inactivo_pero_se_conserva(self):
        usuario = crear_usuario(Rol.PROVEEDOR, proveedor=self.proveedor)
        inactivo = crear_proveedor(razon_social="Inactivo Ficticio")
        Proveedor.objects.filter(pk=inactivo.pk).update(estado=Proveedor.Estado.INACTIVO)
        usuario.proveedor = Proveedor.objects.get(pk=inactivo.pk)
        with self.assertRaises(ValidationError):
            usuario.full_clean()
        Proveedor.objects.filter(pk=self.proveedor.pk).update(estado=Proveedor.Estado.INACTIVO)
        usuario.refresh_from_db()
        usuario.nombre = "Nombre cambiado"
        usuario.full_clean()

    def test_el_proveedor_con_usuarios_no_se_borra(self):
        from django.db.models import ProtectedError

        crear_usuario(Rol.PROVEEDOR, proveedor=self.proveedor)
        with self.assertRaises(ProtectedError):
            self.proveedor.delete()

    def test_panel_de_usuarios_asocia_la_ficha_y_registra_el_cambio(self):
        administrador = crear_usuario(Rol.ADMINISTRADOR, correo="admin@ejemplo.test")
        self.client.force_login(administrador)
        datos = {
            "correo": "portal@ejemplo.test",
            "nombre": "Usuario Portal",
            "rol": Rol.PROVEEDOR,
            "area": "",
            "modo_clave": "generar",
            "motivo": MOTIVO,
        }
        respuesta = self.client.post(reverse("configuracion:usuario_nuevo"), datos)
        self.assertContains(respuesta, "debe estar asociado a la ficha de su proveedor")
        respuesta = self.client.post(reverse("configuracion:usuario_nuevo"), {**datos, "proveedor": self.proveedor.pk})
        self.assertEqual(respuesta.status_code, 302)
        usuario = Usuario.objects.get(correo="portal@ejemplo.test")
        self.assertEqual(usuario.proveedor, self.proveedor)
        registro = RegistroBitacora.objects.filter(accion="usuario.creado", objeto_id=str(usuario.pk)).get()
        self.assertEqual(registro.valor_nuevo["proveedor"]["id"], self.proveedor.pk)
