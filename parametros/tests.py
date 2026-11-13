from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.test import SimpleTestCase, TestCase

from bitacora.models import RegistroBitacora
from cuentas.models import Rol
from cuentas.tests.utilidades import crear_area, crear_usuario
from parametros import servicios
from parametros.catalogo import DEFINICIONES, PERMITIR_DEVOLUCION
from parametros.models import Parametro

MOTIVO = "Decisión ficticia del comité"


class ConversionTests(SimpleTestCase):
    def test_convierte_cada_tipo(self):
        self.assertIs(Parametro.convertir("booleano", "true"), True)
        self.assertIs(Parametro.convertir("booleano", "No"), False)
        self.assertEqual(Parametro.convertir("entero", " 15 "), 15)
        self.assertEqual(Parametro.convertir("decimal", "0.10"), Decimal("0.10"))
        self.assertEqual(Parametro.convertir("texto", "  abc "), "abc")

    def test_rechaza_valores_invalidos(self):
        for tipo, valor in (("booleano", "quizás"), ("entero", "1.5"), ("decimal", "abc"), ("decimal", "NaN"), ("texto", " ")):
            with self.subTest(tipo=tipo, valor=valor), self.assertRaises(ValidationError):
                Parametro.convertir(tipo, valor)


class ParametroD01Tests(TestCase):
    def setUp(self):
        self.administrador = crear_usuario(Rol.ADMINISTRADOR, correo="admin-parametros@ejemplo.test")
        self.coordinador = crear_usuario(Rol.COORDINADOR, correo="coord-parametros@ejemplo.test", area=crear_area())
        self.parametro = Parametro.objects.get(clave=PERMITIR_DEVOLUCION)

    def test_migracion_crea_d01_activado_por_defecto(self):
        self.assertEqual(self.parametro.decision, "D-01")
        self.assertEqual(self.parametro.valor, "true")
        self.assertEqual(self.parametro.valor_por_defecto, DEFINICIONES[PERMITIR_DEVOLUCION].valor_por_defecto)
        self.assertIs(servicios.obtener(PERMITIR_DEVOLUCION), True)

    def test_sin_registro_usa_el_valor_por_defecto_documentado(self):
        Parametro.objects.filter(pk=self.parametro.pk).delete()
        self.assertIs(servicios.obtener(PERMITIR_DEVOLUCION), True)

    def test_parametro_desconocido(self):
        with self.assertRaises(LookupError):
            servicios.obtener("no.existe")

    def test_cambiar_valor_registra_bitacora_con_motivo(self):
        servicios.cambiar_valor(self.parametro, "false", actor=self.administrador, motivo=MOTIVO)
        self.assertIs(servicios.obtener(PERMITIR_DEVOLUCION), False)
        registro = RegistroBitacora.objects.get(accion="parametro.modificado")
        self.assertEqual(registro.valor_anterior, {"valor": "true"})
        self.assertEqual(registro.valor_nuevo, {"valor": "false"})
        self.assertEqual(registro.motivo, MOTIVO)
        self.assertEqual(registro.actor, self.administrador)

    def test_cambiar_valor_exige_motivo_y_valor_distinto_y_valido(self):
        for valor, motivo in (("false", ""), ("true", MOTIVO), ("quizás", MOTIVO)):
            with self.subTest(valor=valor, motivo=motivo), self.assertRaises(ValidationError):
                servicios.cambiar_valor(self.parametro, valor, actor=self.administrador, motivo=motivo)
        self.parametro.refresh_from_db()
        self.assertEqual(self.parametro.valor, "true")
        self.assertFalse(RegistroBitacora.objects.exists())

    def test_solo_administracion_cambia_parametros(self):
        with self.assertRaises(PermissionDenied):
            servicios.cambiar_valor(self.parametro, "false", actor=self.coordinador, motivo=MOTIVO)
        self.parametro.refresh_from_db()
        self.assertEqual(self.parametro.valor, "true")
