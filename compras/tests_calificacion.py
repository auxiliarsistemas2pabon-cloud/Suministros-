import json
from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.test import Client, SimpleTestCase, TestCase
from django.urls import reverse

from bitacora.models import RegistroBitacora
from compras import calificacion_servicios, criterios_servicios, servicios
from compras.calificacion import calcular_puntaje
from compras.models import CalificacionElegible, CriterioElegible, ListaElegibles, VersionCriterios
from cuentas.models import Rol
from cuentas.tests.utilidades import crear_area, crear_usuario
from parametros.catalogo import REGLAS_ELEGIBLES, validar_reglas_elegibles
from parametros.models import Parametro
from parametros.servicios import cambiar_valor
from proveedores.tests.utilidades import crear_proveedor

MOTIVO = "Validación ficticia de la calificación FR-GDS-20"
REGLAS = {"metodo": "directo", "escala": ["5", "3", "1"], "pendiente": True}


class CalculoElegiblesTests(SimpleTestCase):
    def setUp(self):
        self.criterios = [{"id": n, "nombre": nombre, "peso": Decimal(peso)} for n, (nombre, peso) in enumerate([
            ("Administrativos", "30"), ("Precio", "20"), ("Valor agregado", "20"), ("Certificaciones", "30")], 1)]
        self.respuestas = {n: {"cumplimiento": Decimal(valor)} for n, valor in enumerate(["5", "3", "1", "5"], 1)}

    def test_directo_ejemplo_manual_380_sobre_5(self):
        resultado = calcular_puntaje(self.criterios, self.respuestas, REGLAS)
        self.assertEqual([c["subtotal"] for c in resultado["celdas"]], [Decimal("1.5"), Decimal("0.6"), Decimal("0.2"), Decimal("1.5")])
        self.assertEqual(resultado["total"], Decimal("3.8000"))
        self.assertIsInstance(resultado["total"], Decimal)
        self.assertEqual(resultado["maximo"], Decimal(5))

    def test_escalado_ejemplo_manual_76_sobre_100(self):
        resultado = calcular_puntaje(self.criterios, self.respuestas, {**REGLAS, "metodo": "escalado"})
        self.assertEqual([c["subtotal"] for c in resultado["celdas"]], [Decimal(30), Decimal(12), Decimal(4), Decimal(30)])
        self.assertEqual(resultado["total"], Decimal(76))
        self.assertEqual(resultado["maximo"], Decimal(100))

    def test_pendiente_no_es_cero_y_redondeo_es_reproducible(self):
        resultado = calcular_puntaje(self.criterios, {1: self.respuestas[1]}, REGLAS)
        self.assertIsNone(resultado["total"])
        self.assertFalse(resultado["completo"])
        self.assertEqual(resultado["parcial"], Decimal("1.5"))
        reglas = {"metodo": "escalado", "escala": ["7", "2", "0"], "pendiente": True}
        criterios = [{"id": n, "peso": p} for n, p in enumerate(["33.33", "33.33", "33.34"], 1)]
        respuestas = {n: {"cumplimiento": v} for n, v in enumerate(["7", "2", "0"], 1)}
        resultado = calcular_puntaje(criterios, respuestas, reglas)
        self.assertEqual(resultado["total"], Decimal("42.8529"))
        self.assertTrue(resultado["completo"])
        self.assertEqual(resultado["celdas"][-1]["subtotal"], 0)

    def test_pesos_y_respuestas_invalidos_se_rechazan(self):
        with self.assertRaises(ValidationError):
            calcular_puntaje(self.criterios[:-1], self.respuestas, REGLAS)
        for valor in ["NaN", "Infinity", "abc", "4", 0.1, True]:
            with self.subTest(valor=valor), self.assertRaises(ValidationError):
                calcular_puntaje(self.criterios, {1: {"cumplimiento": valor}}, REGLAS)

    def test_validacion_estricta_del_parametro_configurable(self):
        for cambios in [{"metodo": "otro"}, {"escala": ["0", "0"]}, {"escala": ["5", "5", "1"]},
                        {"escala": ["NaN", "1"]}, {"escala": [5.0, "1"]}, {"escala": [True, "1"]},
                        {"escala": ["1.0001", "0"]}, {"escala": ["101", "0"]}, {"pendiente": "no"}]:
            with self.subTest(cambios=cambios), self.assertRaises(ValidationError):
                validar_reglas_elegibles(json.dumps({**REGLAS, **cambios}))
        self.assertEqual(json.loads(validar_reglas_elegibles(json.dumps(REGLAS))), REGLAS)


class CalificacionElegiblesTests(TestCase):
    def setUp(self):
        self.area = crear_area()
        self.admin = crear_usuario(Rol.ADMINISTRADOR)
        self.dev = crear_usuario(Rol.DESARROLLADOR)
        self.coordinador = crear_usuario(Rol.COORDINADOR, area=self.area)
        self.usuario_proveedor = crear_usuario(Rol.PROVEEDOR)
        self.ficha = self.usuario_proveedor.proveedor
        self.fecha = date(2031, 2, 1)
        self.version = VersionCriterios.objects.get(numero=1)
        self.necesidad = servicios.crear_necesidad(objeto="Compra ficticia para calificar", area=self.area,
            fecha=self.fecha, origen_texto="Solicitud ficticia", actor=self.admin, motivo=MOTIVO)

    def publicar(self, version=None, desde=None, hasta=None):
        return criterios_servicios.publicar_version(version or self.version, desde=desde or date(2031, 1, 1), hasta=hasta, actor=self.admin, motivo=MOTIVO)

    def lista(self):
        lista = servicios.crear_lista(self.necesidad, fecha=self.fecha, actor=self.admin, motivo=MOTIVO)
        servicios.agregar_participante(lista, self.ficha, actor=self.admin, motivo=MOTIVO)
        return lista

    def celdas(self, lista, valores=("5", "3", "1", "5")):
        return [{"participante": p.pk, "criterio": c.pk, "cumplimiento": Decimal(v) if v is not None else None,
                 "observacion": "Evidencia ficticia"} for p in lista.participantes.filter(activo=True)
                for c, v in zip(lista.version_criterios.criterios.all(), valores)]

    def guardar(self, lista, celdas=None):
        return calificacion_servicios.guardar_matriz(lista, self.celdas(lista) if celdas is None else celdas, actor=self.admin, motivo=MOTIVO)

    def test_catalogo_inicial_en_borrador_y_lista_sin_version(self):
        self.assertEqual(self.version.estado, "borrador")
        self.assertEqual(list(self.version.criterios.values_list("peso", flat=True)), [Decimal(30), Decimal(20), Decimal(20), Decimal(30)])
        lista = self.lista()
        self.assertIsNone(lista.version_criterios_id)
        self.assertFalse(calificacion_servicios.obtener_matriz(lista)["completa"])
        self.publicar()
        lista = criterios_servicios.configurar_lista(lista, self.version, actor=self.admin, motivo=MOTIVO)
        self.assertEqual(lista.version_criterios, self.version)
        self.assertEqual(lista.reglas_calculo, REGLAS)
        with self.assertRaises(ValidationError):
            criterios_servicios.configurar_lista(lista, self.version, actor=self.admin, motivo=MOTIVO)

    def test_editar_pesos_total_y_nombres_invalidos_no_dejan_cambios(self):
        originales = list(self.version.criterios.values("nombre", "peso"))
        for filas in [[{"nombre": "Uno", "peso": "99"}], [{"nombre": "Precio", "peso": "50"}, {"nombre": " precio ", "peso": "50"}],
                      [{"nombre": "Uno", "peso": "NaN"}], [{"nombre": "Uno", "peso": 100.0}]]:
            with self.subTest(filas=filas), self.assertRaises(ValidationError):
                criterios_servicios.guardar_borrador(self.version, criterios=filas, notas="Cambio", actor=self.admin, motivo=MOTIVO)
            self.assertEqual(list(self.version.criterios.values("nombre", "peso")), originales)
        criterios_servicios.guardar_borrador(self.version, criterios=[{"nombre": "Criterio ficticio", "peso": "100"}], notas="Notas ficticias", actor=self.dev, motivo=MOTIVO)
        self.assertEqual(self.version.criterios.count(), 1)
        self.assertTrue(RegistroBitacora.objects.filter(accion="criterios.editados", actor=self.dev).exists())

    def test_publicar_rechaza_pesos_incompletos_y_vigencias_solapadas(self):
        criterio = self.version.criterios.first()
        criterio.peso = Decimal(29)
        criterio.save()
        with self.assertRaises(ValidationError):
            self.publicar()
        criterio.peso = Decimal(30)
        criterio.save()
        self.publicar(hasta=date(2031, 12, 31))
        nueva = criterios_servicios.copiar_version(self.version, actor=self.admin, motivo=MOTIVO)
        with self.assertRaises(ValidationError):
            self.publicar(nueva, desde=date(2031, 7, 1))
        with self.assertRaises(ValidationError):
            self.publicar(nueva, desde=date(2032, 1, 2), hasta=date(2032, 1, 1))
        self.publicar(nueva, desde=date(2032, 1, 1))
        self.assertEqual(criterios_servicios.versiones_en_fecha(date(2031, 12, 31)).get(), self.version)
        self.assertEqual(criterios_servicios.versiones_en_fecha(date(2032, 1, 1)).get(), nueva)

    def test_publicados_se_conservan_tambien_por_orm(self):
        self.publicar()
        self.version.refresh_from_db()
        criterio = self.version.criterios.first()
        for operacion in [lambda: self.version.save(), lambda: self.version.delete(),
                          lambda: VersionCriterios.objects.filter(pk=self.version.pk).update(notas="Otra"),
                          lambda: criterio.save(), lambda: criterio.delete(),
                          lambda: self.version.criterios.update(peso=10), lambda: self.version.criterios.all().delete(),
                          lambda: CriterioElegible.objects.bulk_create([CriterioElegible(version=self.version, orden=9, nombre="Otro", peso=10)])]:
            with self.assertRaises(ValidationError):
                operacion()

    def test_matriz_guarda_valores_observaciones_y_auditoria_unica_por_celda(self):
        self.publicar()
        lista = self.lista()
        self.guardar(lista)
        matriz = calificacion_servicios.obtener_matriz(lista)
        self.assertTrue(matriz["completa"])
        self.assertEqual(matriz["filas"][0]["total"], Decimal("3.8"))
        self.assertEqual(CalificacionElegible.objects.count(), 4)
        self.assertEqual(RegistroBitacora.objects.filter(accion="elegible.calificado", actor=self.admin, motivo=MOTIVO).count(), 4)
        self.guardar(lista)
        self.assertEqual(CalificacionElegible.objects.count(), 4)
        self.assertEqual(RegistroBitacora.objects.filter(accion="elegible.calificado").count(), 4)
        nuevos = self.celdas(lista)
        nuevos[0]["cumplimiento"] = Decimal(1)
        self.guardar(lista, nuevos)
        registro = RegistroBitacora.objects.get(accion="elegible.calificacion_modificada")
        self.assertEqual(Decimal(registro.valor_anterior["cumplimiento"]), 5)
        self.assertEqual(Decimal(registro.valor_nuevo["cumplimiento"]), 1)
        self.assertEqual(CalificacionElegible.objects.first().observacion, "Evidencia ficticia")
        fila = CalificacionElegible.objects.first()
        with self.assertRaises(IntegrityError), transaction.atomic():
            CalificacionElegible.objects.create(participante=fila.participante, criterio=fila.criterio, cumplimiento=Decimal(3))

    def test_parametros_y_nuevas_versiones_no_cambian_lista_cerrada(self):
        self.publicar()
        lista = self.lista()
        self.guardar(lista)
        ListaElegibles.objects.filter(pk=lista.pk).update(estado="cerrada")
        parametro = Parametro.objects.get(clave=REGLAS_ELEGIBLES)
        cambiar_valor(parametro, json.dumps({**REGLAS, "metodo": "escalado"}), actor=self.admin, motivo=MOTIVO)
        nueva = criterios_servicios.copiar_version(self.version, actor=self.admin, motivo=MOTIVO)
        criterios_servicios.guardar_borrador(nueva, criterios=[{"nombre": "Otro criterio ficticio", "peso": "100"}], notas="Nueva versión", actor=self.admin, motivo=MOTIVO)
        self.publicar(nueva, desde=date(2032, 1, 1))
        lista.refresh_from_db()
        self.assertEqual(lista.version_criterios_id, self.version.pk)
        self.assertEqual(lista.reglas_calculo["metodo"], "directo")
        self.assertEqual(calificacion_servicios.obtener_matriz(lista)["filas"][0]["total"], Decimal("3.8"))
        nueva_lista = self.lista()
        self.assertEqual(nueva_lista.reglas_calculo["metodo"], "escalado")
        self.guardar(nueva_lista)
        self.assertEqual(calificacion_servicios.obtener_matriz(nueva_lista)["filas"][0]["total"], Decimal(76))

    def test_estados_inactividad_y_criterio_ajeno_impiden_modificaciones(self):
        self.publicar()
        lista = self.lista()
        self.guardar(lista)
        for estado in ["cerrada", "anulada"]:
            ListaElegibles.objects.filter(pk=lista.pk).update(estado=estado)
            with self.assertRaises(ValidationError):
                self.guardar(lista)
            respuesta = CalificacionElegible.objects.first()
            with self.assertRaises(ValidationError):
                respuesta.save()
        ListaElegibles.objects.filter(pk=lista.pk).update(estado="borrador")
        celdas = self.celdas(lista)
        celdas[0]["criterio"] = 999999
        with self.assertRaises(ValidationError):
            self.guardar(lista, celdas)
        participante = lista.participantes.get()
        servicios.quitar_participante(lista, participante, actor=self.admin, motivo=MOTIVO)
        self.assertFalse(calificacion_servicios.obtener_matriz(lista)["filas"])
        with self.assertRaises(ValidationError):
            self.guardar(lista, [{"participante": participante.pk, "criterio": 1, "cumplimiento": Decimal(5)}])

    def test_guardado_atomico_ante_valor_invalido_y_fallo_de_auditoria(self):
        self.publicar()
        lista = self.lista()
        for valor in ["NaN", "4", True, 5.0]:
            celdas = self.celdas(lista)
            celdas[-1]["cumplimiento"] = valor
            with self.assertRaises(ValidationError):
                self.guardar(lista, celdas)
            self.assertFalse(CalificacionElegible.objects.exists())
        with patch("compras.calificacion_servicios.guardar_con_bitacora", side_effect=RuntimeError("Fallo ficticio")):
            with self.assertRaises(RuntimeError):
                self.guardar(lista)
        self.assertFalse(CalificacionElegible.objects.exists())

    def test_formulario_matriz_guarda_y_rechaza_miembros_cambiados(self):
        self.publicar()
        lista = self.lista()
        self.client.force_login(self.admin)
        url = reverse("compras:lista_calificar", args=[lista.pk])
        respuesta = self.client.get(url)
        self.assertContains(respuesta, "D-07 pendiente")
        formulario = respuesta.context["formulario"]
        datos = {"revision": formulario["revision"].value(), "motivo": MOTIVO}
        for _, _, clave, observacion in formulario.celdas:
            datos[clave], datos[observacion] = "5", "Verificación ficticia"
        self.assertRedirects(self.client.post(url, datos), url)
        self.assertEqual(calificacion_servicios.obtener_matriz(lista)["filas"][0]["total"], Decimal(5))
        servicios.agregar_participante(lista, crear_proveedor(), actor=self.admin, motivo=MOTIVO)
        respuesta = self.client.post(url, datos)
        self.assertContains(respuesta, "Recargue la matriz")
        self.assertEqual(CalificacionElegible.objects.count(), 4)
        cliente_csrf = Client(enforce_csrf_checks=True)
        cliente_csrf.force_login(self.admin)
        self.assertEqual(cliente_csrf.post(url, datos).status_code, 403)

    def test_configuracion_y_publicacion_desde_pantallas(self):
        self.client.force_login(self.dev)
        lista = self.lista()
        url = reverse("compras:lista_calificar", args=[lista.pk])
        self.assertContains(self.client.get(url), "todavía no tiene versión")
        respuesta = self.client.post(reverse("compras:version_criterios_publicar", args=[self.version.pk]),
            {"publicacion-desde": "2031-01-01", "publicacion-hasta": "", "publicacion-motivo": MOTIVO})
        self.assertEqual(respuesta.status_code, 302)
        respuesta = self.client.post(reverse("compras:lista_configurar", args=[lista.pk]), {"version": self.version.pk, "motivo": MOTIVO})
        self.assertRedirects(respuesta, url)
        respuesta = self.client.post(reverse("compras:version_criterios_copiar", args=[self.version.pk]), {"motivo": MOTIVO})
        nueva = VersionCriterios.objects.get(numero=2)
        self.assertRedirects(respuesta, reverse("compras:version_criterios_detalle", args=[nueva.pk]))
        datos = {"edicion-notas": "Notas ficticias", "edicion-motivo": MOTIVO, "criterios-TOTAL_FORMS": "1", "criterios-INITIAL_FORMS": "0",
                 "criterios-0-nombre": "Nuevo criterio ficticio", "criterios-0-peso": "100"}
        self.assertEqual(self.client.post(respuesta.url, datos).status_code, 302)
        self.assertEqual(nueva.criterios.get().nombre, "Nuevo criterio ficticio")

    def test_permisos_vistas_y_servicios_y_motivo_obligatorio(self):
        self.publicar()
        lista = self.lista()
        lecturas = [reverse("compras:versiones_criterios"), reverse("compras:version_criterios_detalle", args=[self.version.pk]), reverse("compras:lista_calificar", args=[lista.pk])]
        escrituras = [reverse("compras:version_criterios_copiar", args=[self.version.pk]), reverse("compras:version_criterios_publicar", args=[self.version.pk]), reverse("compras:lista_configurar", args=[lista.pk])]
        for usuario in [self.coordinador, self.usuario_proveedor]:
            self.client.force_login(usuario)
            for url in lecturas + escrituras:
                self.assertEqual(self.client.get(url).status_code, 403)
                self.assertEqual(self.client.post(url, {}).status_code, 403)
        for usuario in [self.admin, self.dev]:
            self.client.force_login(usuario)
            for url in lecturas:
                self.assertEqual(self.client.get(url).status_code, 200)
            for url in escrituras:
                self.assertEqual(self.client.get(url).status_code, 405)
        operaciones = [lambda actor, motivo: criterios_servicios.copiar_version(self.version, actor=actor, motivo=motivo),
            lambda actor, motivo: criterios_servicios.publicar_version(self.version, desde=self.fecha, actor=actor, motivo=motivo),
            lambda actor, motivo: criterios_servicios.guardar_borrador(self.version, criterios=[], notas="", actor=actor, motivo=motivo),
            lambda actor, motivo: criterios_servicios.configurar_lista(lista, self.version, actor=actor, motivo=motivo),
            lambda actor, motivo: calificacion_servicios.guardar_matriz(lista, self.celdas(lista), actor=actor, motivo=motivo)]
        for operacion in operaciones:
            for actor in [self.coordinador, self.usuario_proveedor, AnonymousUser()]:
                with self.assertRaises(PermissionDenied):
                    operacion(actor, MOTIVO)
            with self.assertRaises(ValidationError):
                operacion(self.admin, " ")
