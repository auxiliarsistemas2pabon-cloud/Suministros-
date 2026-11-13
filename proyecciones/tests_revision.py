"""GDS-PRY-04: revisión, corrección y devolución de proyecciones por administración."""

from datetime import date
from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from bitacora.models import RegistroBitacora
from cuentas.models import Rol
from cuentas.tests.utilidades import crear_area, crear_usuario
from parametros.catalogo import PERMITIR_DEVOLUCION
from parametros.models import Parametro
from proyecciones import servicios
from proyecciones.models import CAMPOS_CANTIDADES_MENSUALES, Linea, Periodo, ProyeccionArea, UnidadMedida

MOTIVO = "Corrección ficticia acordada con el área"


class BaseRevision(TestCase):
    def setUp(self):
        self.area = crear_area("Farmacia", "FAR")
        self.otra_area = crear_area("Laboratorio", "LAB")
        self.administrador = crear_usuario(Rol.ADMINISTRADOR, correo="admin-revision@ejemplo.test")
        self.desarrollador = crear_usuario(Rol.DESARROLLADOR, correo="dev-revision@ejemplo.test")
        self.coordinador = crear_usuario(Rol.COORDINADOR, correo="coord-revision@ejemplo.test", area=self.area)
        self.proveedor = crear_usuario(Rol.PROVEEDOR, correo="prov-revision@ejemplo.test")
        self.unidad = UnidadMedida.objects.create(nombre="Caja", abreviatura="cja")
        self.otra_unidad = UnidadMedida.objects.create(nombre="Frasco", abreviatura="fco")
        self.periodo = Periodo.objects.create(
            anio=2031,
            fecha_apertura=date(2031, 1, 1),
            fecha_limite_diligenciamiento=date(2031, 12, 15),
            creado_por=self.administrador,
        )
        self.proyeccion = ProyeccionArea.objects.create(
            periodo=self.periodo,
            area=self.area,
            estado=ProyeccionArea.Estado.ENVIADA,
            fecha_envio=timezone.now(),
            enviado_por=self.coordinador,
        )
        self.otra_proyeccion = ProyeccionArea.objects.create(periodo=self.periodo, area=self.otra_area)
        self.linea = Linea.objects.create(
            proyeccion=self.proyeccion,
            producto_servicio="Guantes de examen",
            dependencia="Urgencias",
            unidad=self.unidad,
            cantidad_enero=2,
            cantidad_febrero=3,
            precio_estimado=Decimal("12.50"),
        )
        self.linea_dos = Linea.objects.create(
            proyeccion=self.proyeccion,
            producto_servicio="Jeringas de 5 ml",
            unidad=self.unidad,
            cantidad_enero=10,
            precio_estimado=Decimal("1.10"),
        )
        self.linea_ajena = Linea.objects.create(
            proyeccion=self.otra_proyeccion,
            producto_servicio="Reactivo ficticio",
            unidad=self.unidad,
            cantidad_enero=1,
            precio_estimado=Decimal("100.00"),
        )
        self.url_detalle = reverse("proyecciones:revision_detalle", args=[self.proyeccion.pk])
        self.url_corregir = reverse("proyecciones:revision_corregir_linea", args=[self.proyeccion.pk, self.linea.pk])
        self.url_devolver = reverse("proyecciones:revision_devolver", args=[self.proyeccion.pk])

    def datos_correccion(self, linea=None, **cambios):
        linea = linea or self.linea
        datos = {
            "producto_servicio": linea.producto_servicio,
            "dependencia": linea.dependencia,
            "unidad": str(linea.unidad_id),
            "precio_estimado": str(linea.precio_estimado),
            "motivo": MOTIVO,
        }
        for campo in CAMPOS_CANTIDADES_MENSUALES:
            datos[campo] = str(getattr(linea, campo))
        datos.update(cambios)
        return datos


class ListadoRevisionTests(BaseRevision):
    def test_lista_estado_lineas_y_costo_total_con_decimal(self):
        self.client.force_login(self.administrador)
        respuesta = self.client.get(reverse("proyecciones:revision"))
        self.assertEqual(respuesta.status_code, 200)
        filas = {fila.area.codigo_area: fila for fila in respuesta.context["pagina"]}
        self.assertEqual(set(filas), {"FAR", "LAB"})
        self.assertEqual(filas["FAR"].numero_lineas, 2)
        # (2 + 3) × 12,50 + 10 × 1,10 = 62,50 + 11,00
        self.assertEqual(filas["FAR"].costo_total, Decimal("73.50"))
        self.assertIsInstance(filas["FAR"].costo_total, Decimal)
        self.assertEqual(filas["LAB"].costo_total, Decimal("100.00"))
        self.assertEqual(respuesta.context["costo_total"], Decimal("173.50"))
        self.assertContains(respuesta, "73,50")

    def test_proyeccion_sin_lineas_tiene_costo_cero(self):
        Linea.objects.filter(proyeccion=self.otra_proyeccion).delete()
        consulta = servicios.resumen_revision(servicios.filtrar_proyecciones(area=self.otra_area))
        self.assertEqual(consulta.get().costo_total, Decimal("0"))
        self.assertEqual(consulta.get().numero_lineas, 0)

    def test_filtros_por_periodo_area_y_estado(self):
        otro_periodo = Periodo.objects.create(
            anio=2030,
            fecha_apertura=date(2030, 1, 1),
            fecha_limite_diligenciamiento=date(2030, 12, 15),
            creado_por=self.administrador,
            estado=Periodo.Estado.CERRADO,
        )
        ProyeccionArea.objects.create(periodo=otro_periodo, area=self.area)
        self.client.force_login(self.administrador)
        url = reverse("proyecciones:revision")
        casos = [
            ({"periodo": otro_periodo.pk}, {(2030, "FAR")}),
            ({"periodo": "", "area": self.area.pk}, {(2031, "FAR"), (2030, "FAR")}),
            ({"periodo": self.periodo.pk, "estado": "enviada"}, {(2031, "FAR")}),
            ({"periodo": self.periodo.pk, "estado": "borrador"}, {(2031, "LAB")}),
            ({"periodo": ""}, {(2031, "FAR"), (2031, "LAB"), (2030, "FAR")}),
        ]
        for filtros, esperado in casos:
            with self.subTest(filtros=filtros):
                respuesta = self.client.get(url, filtros)
                obtenido = {(p.periodo.anio, p.area.codigo_area) for p in respuesta.context["pagina"]}
                self.assertEqual(obtenido, esperado)

    def test_sin_filtros_muestra_el_periodo_abierto_mas_reciente(self):
        anterior = Periodo.objects.create(
            anio=2029,
            fecha_apertura=date(2029, 1, 1),
            fecha_limite_diligenciamiento=date(2029, 12, 15),
            creado_por=self.administrador,
        )
        ProyeccionArea.objects.create(periodo=anterior, area=self.area)
        self.client.force_login(self.administrador)
        for parametros in ({}, {"pagina": "1"}):
            with self.subTest(parametros=parametros):
                respuesta = self.client.get(reverse("proyecciones:revision"), parametros)
                self.assertEqual({p.periodo.anio for p in respuesta.context["pagina"]}, {2031})


class CorreccionTests(BaseRevision):
    def test_correccion_sin_motivo_se_rechaza(self):
        self.client.force_login(self.administrador)
        respuesta = self.client.post(self.url_corregir, self.datos_correccion(cantidad_enero="7", motivo="  "))
        self.assertEqual(respuesta.status_code, 200)
        self.assertTrue(respuesta.context["formulario"].errors["motivo"])
        self.linea.refresh_from_db()
        self.assertEqual(self.linea.cantidad_enero, 2)
        self.assertFalse(RegistroBitacora.objects.filter(accion="linea.corregida").exists())

    def test_servicio_rechaza_correccion_sin_motivo(self):
        self.linea.cantidad_enero = 7
        with self.assertRaises(ValidationError):
            servicios.corregir_linea(self.linea, actor=self.administrador, motivo="")
        self.linea.refresh_from_db()
        self.assertEqual(self.linea.cantidad_enero, 2)

    def test_correccion_guarda_autor_valor_anterior_nuevo_y_justificacion(self):
        self.client.force_login(self.administrador)
        respuesta = self.client.post(
            self.url_corregir,
            self.datos_correccion(
                cantidad_enero="7",
                precio_estimado="15.00",
                unidad=str(self.otra_unidad.pk),
                producto_servicio="Guantes de nitrilo",
            ),
        )
        self.assertRedirects(respuesta, self.url_detalle)
        self.linea.refresh_from_db()
        self.assertEqual(self.linea.cantidad_enero, 7)
        self.assertEqual(self.linea.precio_estimado, Decimal("15.00"))
        self.assertEqual(self.linea.costo_anual, Decimal("150.00"))

        registro = RegistroBitacora.objects.get(accion="linea.corregida", objeto_id=str(self.linea.pk))
        self.assertEqual(registro.actor, self.administrador)
        self.assertEqual(registro.actor_texto, "admin-revision@ejemplo.test")
        self.assertEqual(registro.motivo, MOTIVO)
        self.assertEqual(
            registro.valor_anterior,
            {
                "producto_servicio": "Guantes de examen",
                "unidad": {"id": self.unidad.pk, "texto": str(self.unidad)},
                "cantidad_enero": 2,
                "precio_estimado": "12.50",
            },
        )
        self.assertEqual(
            registro.valor_nuevo,
            {
                "producto_servicio": "Guantes de nitrilo",
                "unidad": {"id": self.otra_unidad.pk, "texto": str(self.otra_unidad)},
                "cantidad_enero": 7,
                "precio_estimado": "15.00",
            },
        )
        # La proyección sigue enviada y la corrección aparece en su historial.
        self.proyeccion.refresh_from_db()
        self.assertEqual(self.proyeccion.estado, ProyeccionArea.Estado.ENVIADA)
        self.assertContains(self.client.get(self.url_detalle), "linea.corregida")

    def test_correccion_sin_cambios_se_rechaza(self):
        self.client.force_login(self.administrador)
        respuesta = self.client.post(self.url_corregir, self.datos_correccion())
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, "No hay cambios para guardar")
        self.assertFalse(RegistroBitacora.objects.filter(accion="linea.corregida").exists())

    def test_correccion_valida_cantidades_y_unidad(self):
        inactiva = UnidadMedida.objects.create(nombre="Sobre", abreviatura="sob", activa=False)
        self.client.force_login(self.administrador)
        for cambios in ({"cantidad_enero": "-1"}, {"cantidad_enero": "1.5"}, {"unidad": str(inactiva.pk)}):
            with self.subTest(cambios=cambios):
                respuesta = self.client.post(self.url_corregir, self.datos_correccion(**cambios))
                self.assertEqual(respuesta.status_code, 200)
                self.assertTrue(respuesta.context["formulario"].errors)
        self.linea.refresh_from_db()
        self.assertEqual(self.linea.cantidad_enero, 2)
        self.assertEqual(self.linea.unidad, self.unidad)

    def test_solo_se_corrige_una_proyeccion_enviada(self):
        self.client.force_login(self.administrador)
        url = reverse("proyecciones:revision_corregir_linea", args=[self.otra_proyeccion.pk, self.linea_ajena.pk])
        respuesta = self.client.post(url, self.datos_correccion(self.linea_ajena, cantidad_enero="9"))
        self.assertRedirects(
            respuesta, reverse("proyecciones:revision_detalle", args=[self.otra_proyeccion.pk])
        )
        self.linea_ajena.refresh_from_db()
        self.assertEqual(self.linea_ajena.cantidad_enero, 1)
        self.linea_ajena.cantidad_enero = 9
        with self.assertRaises(ValidationError):
            servicios.corregir_linea(self.linea_ajena, actor=self.administrador, motivo=MOTIVO)

    def test_linea_de_otra_proyeccion_por_url_da_404(self):
        self.client.force_login(self.administrador)
        url = reverse("proyecciones:revision_corregir_linea", args=[self.proyeccion.pk, self.linea_ajena.pk])
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.post(url, self.datos_correccion(self.linea_ajena)).status_code, 404)

    def test_servicio_exige_rol_de_administracion(self):
        self.linea.cantidad_enero = 9
        for usuario in (self.coordinador, self.proveedor):
            with self.subTest(rol=usuario.rol), self.assertRaises(PermissionDenied):
                servicios.corregir_linea(self.linea, actor=usuario, motivo=MOTIVO)
        self.linea.refresh_from_db()
        self.assertEqual(self.linea.cantidad_enero, 2)


class DevolucionTests(BaseRevision):
    def test_devolver_cambia_a_borrador_y_guarda_bitacora(self):
        self.client.force_login(self.administrador)
        respuesta = self.client.post(self.url_devolver, {"motivo": "Faltan insumos de urgencias (ficticio)"})
        self.assertRedirects(respuesta, self.url_detalle)
        self.proyeccion.refresh_from_db()
        self.assertEqual(self.proyeccion.estado, ProyeccionArea.Estado.BORRADOR)
        self.assertIsNone(self.proyeccion.fecha_envio)
        self.assertIsNone(self.proyeccion.enviado_por)
        registro = RegistroBitacora.objects.get(accion="proyeccion_area.devuelta")
        self.assertEqual(registro.actor, self.administrador)
        self.assertEqual(registro.motivo, "Faltan insumos de urgencias (ficticio)")
        self.assertEqual(registro.valor_anterior["estado"], "enviada")
        self.assertEqual(registro.valor_anterior["enviado_por"]["id"], self.coordinador.pk)
        self.assertIsNotNone(registro.valor_anterior["fecha_envio"])
        self.assertEqual(registro.valor_nuevo["estado"], "borrador")
        self.assertIsNone(registro.valor_nuevo["enviado_por"])

    def test_area_ve_el_motivo_y_puede_volver_a_editar(self):
        servicios.devolver_proyeccion(self.proyeccion, actor=self.administrador, motivo="Revise cantidades de enero")
        self.client.force_login(self.coordinador)
        respuesta = self.client.get(reverse("proyecciones:mi_proyeccion"))
        self.assertContains(respuesta, "Administración devolvió esta proyección")
        self.assertContains(respuesta, "Revise cantidades de enero")
        self.assertTrue(respuesta.context["editable"])

    def test_devolver_sin_motivo_se_rechaza(self):
        self.client.force_login(self.administrador)
        self.client.post(self.url_devolver, {"motivo": ""})
        self.proyeccion.refresh_from_db()
        self.assertEqual(self.proyeccion.estado, ProyeccionArea.Estado.ENVIADA)
        self.assertFalse(RegistroBitacora.objects.filter(accion="proyeccion_area.devuelta").exists())

    def test_parametro_d01_desactivado_bloquea_la_devolucion(self):
        Parametro.objects.filter(clave=PERMITIR_DEVOLUCION).update(valor="false")
        self.client.force_login(self.administrador)
        self.assertNotContains(self.client.get(self.url_detalle), "Devolver al área</button>")
        respuesta = self.client.post(self.url_devolver, {"motivo": MOTIVO}, follow=True)
        self.assertContains(respuesta, "parámetro D-01")
        self.proyeccion.refresh_from_db()
        self.assertEqual(self.proyeccion.estado, ProyeccionArea.Estado.ENVIADA)

    def test_por_defecto_la_devolucion_esta_activada(self):
        self.assertTrue(servicios.devolucion_habilitada())
        self.client.force_login(self.administrador)
        self.assertContains(self.client.get(self.url_detalle), "Devolver al área</button>")

    def test_periodo_cerrado_bloquea_la_devolucion(self):
        Periodo.objects.filter(pk=self.periodo.pk).update(estado=Periodo.Estado.CERRADO)
        with self.assertRaises(ValidationError):
            servicios.devolver_proyeccion(self.proyeccion, actor=self.administrador, motivo=MOTIVO)
        self.proyeccion.refresh_from_db()
        self.assertEqual(self.proyeccion.estado, ProyeccionArea.Estado.ENVIADA)

    def test_solo_se_devuelve_una_proyeccion_enviada(self):
        with self.assertRaises(ValidationError):
            servicios.devolver_proyeccion(self.otra_proyeccion, actor=self.administrador, motivo=MOTIVO)

    def test_servicio_exige_rol_de_administracion(self):
        with self.assertRaises(PermissionDenied):
            servicios.devolver_proyeccion(self.proyeccion, actor=self.coordinador, motivo=MOTIVO)
        self.proyeccion.refresh_from_db()
        self.assertEqual(self.proyeccion.estado, ProyeccionArea.Estado.ENVIADA)


class PermisosRevisionTests(BaseRevision):
    def urls(self):
        return [
            reverse("proyecciones:revision"),
            self.url_detalle,
            self.url_corregir,
            self.url_devolver,
            reverse("bitacora:consulta"),
        ]

    def assert_sin_cambios(self):
        self.linea.refresh_from_db()
        self.proyeccion.refresh_from_db()
        self.assertEqual(self.linea.cantidad_enero, 2)
        self.assertEqual(self.proyeccion.estado, ProyeccionArea.Estado.ENVIADA)
        self.assertFalse(RegistroBitacora.objects.exists())

    def test_coordinador_y_proveedor_reciben_403_en_get_y_post(self):
        for usuario in (self.coordinador, self.proveedor):
            self.client.force_login(usuario)
            for url in self.urls():
                with self.subTest(rol=usuario.rol, url=url):
                    self.assertEqual(self.client.get(url).status_code, 403)
                    self.assertEqual(
                        self.client.post(url, self.datos_correccion(cantidad_enero="9")).status_code, 403
                    )
                    self.assert_sin_cambios()

    def test_sin_sesion_redirige_al_ingreso(self):
        ingreso = reverse("cuentas:ingresar")
        for url in self.urls():
            with self.subTest(url=url):
                respuesta = self.client.post(url, self.datos_correccion(cantidad_enero="9"))
                self.assertEqual(respuesta.status_code, 302)
                self.assertTrue(respuesta["Location"].startswith(ingreso))
                self.assert_sin_cambios()

    def test_administrador_y_desarrollador_entran(self):
        for usuario in (self.administrador, self.desarrollador):
            self.client.force_login(usuario)
            for url in self.urls():
                if url == self.url_devolver:
                    continue  # Solo POST.
                with self.subTest(rol=usuario.rol, url=url):
                    self.assertEqual(self.client.get(url).status_code, 200)

    def test_devolver_solo_acepta_post(self):
        self.client.force_login(self.administrador)
        self.assertEqual(self.client.get(self.url_devolver).status_code, 405)

    def test_proyeccion_inexistente_da_404(self):
        self.client.force_login(self.administrador)
        self.assertEqual(
            self.client.get(reverse("proyecciones:revision_detalle", args=[999999])).status_code, 404
        )
