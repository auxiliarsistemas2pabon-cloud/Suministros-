from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from bitacora.models import RegistroBitacora
from cuentas.models import Rol
from cuentas.tests.utilidades import crear_usuario
from proveedores import nit, servicios
from proveedores.models import Proveedor
from proveedores.tests.utilidades import DV_FICTICIO, MOTIVO, NIT_FICTICIO, crear_proveedor

FORMATOS_DEL_MISMO_NIT = [
    "900123456",
    "900.123.456",
    "900 123 456",
    "900-123-456",
    "900.123.456-8",
    "900123456-8",
    " 900 123 456 - 8 ",
    "0900123456",
]


class NormalizarNitTests(SimpleTestCase):
    def test_formatos_distintos_dan_el_mismo_nit_canonico(self):
        for texto in FORMATOS_DEL_MISMO_NIT:
            with self.subTest(texto=texto):
                self.assertEqual(nit.normalizar(texto), (NIT_FICTICIO, DV_FICTICIO))

    def test_digito_de_verificacion_dian(self):
        # Valores calculados a mano con los pesos de la DIAN.
        self.assertEqual(nit.calcular_dv("900123456"), 8)
        self.assertEqual(nit.calcular_dv("800000001"), 1)  # residuo 1 → el dígito es el residuo
        self.assertEqual(nit.calcular_dv("12345"), 8)  # residuo 3 → 11 - 3

    def test_digito_de_verificacion_errado(self):
        with self.assertRaises(ValidationError) as contexto:
            nit.normalizar("900.123.456-1")
        self.assertIn("debería ser 8", contexto.exception.messages[0])

    def test_textos_invalidos(self):
        for texto in ("", "ABC123456", "900,123,456", "1234", "1" * 16, "900_123_456"):
            with self.subTest(texto=texto), self.assertRaises(ValidationError):
                nit.normalizar(texto)

    def test_formatear_y_digitos_para_buscar(self):
        self.assertEqual(nit.formatear("900123456", 8), "900.123.456-8")
        self.assertEqual(nit.digitos_para_buscar("900.123.456-8"), "900123456")
        self.assertEqual(nit.digitos_para_buscar("123.45"), "12345")
        self.assertEqual(nit.digitos_para_buscar("Suministros"), "")


class NitUnicoTests(TestCase):
    def setUp(self):
        self.administrador = crear_usuario(Rol.ADMINISTRADOR, correo="admin@ejemplo.test")

    def test_el_modelo_guarda_la_forma_canonica_y_el_dv_aparte(self):
        proveedor = crear_proveedor(nit="900.123.456-8")
        proveedor.refresh_from_db()
        self.assertEqual(proveedor.nit, NIT_FICTICIO)
        self.assertEqual(proveedor.digito_verificacion, DV_FICTICIO)
        self.assertEqual(proveedor.nit_formateado, "900.123.456-8")

    def test_el_mismo_nit_en_otro_formato_no_se_duplica(self):
        crear_proveedor(nit="900123456")
        for texto in FORMATOS_DEL_MISMO_NIT:
            with self.subTest(texto=texto), self.assertRaises(ValidationError) as contexto:
                crear_proveedor(nit=texto, razon_social="Otra Razón Social Ficticia")
            self.assertIn("Ya existe un proveedor con este NIT.", contexto.exception.message_dict["nit"])
        self.assertEqual(Proveedor.objects.count(), 1)

    def test_el_servicio_tampoco_lo_duplica(self):
        servicios.guardar_proveedor(
            Proveedor(**self._datos(nit="900.123.456-8")), actor=self.administrador, motivo=MOTIVO
        )
        with self.assertRaises(ValidationError):
            servicios.guardar_proveedor(Proveedor(**self._datos(nit="900 123 456")), actor=self.administrador, motivo=MOTIVO)
        self.assertEqual(Proveedor.objects.count(), 1)

    def test_la_base_rechaza_un_nit_no_canonico_o_repetido(self):
        crear_proveedor(nit="900123456")
        with self.assertRaises(IntegrityError), transaction.atomic():
            Proveedor.objects.filter(nit=NIT_FICTICIO).update(nit="900.123.456")
        with self.assertRaises(IntegrityError), transaction.atomic():
            Proveedor.objects.bulk_create([Proveedor(**self._datos(nit=NIT_FICTICIO), digito_verificacion=8)])

    def test_formulario_de_creacion_rechaza_el_duplicado(self):
        crear_proveedor(nit="900123456")
        self.client.force_login(self.administrador)
        respuesta = self.client.post(reverse("proveedores:nuevo"), {**self._datos(nit="900.123.456-8"), "motivo": MOTIVO})
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, "Ya existe un proveedor con este NIT.")
        self.assertEqual(Proveedor.objects.count(), 1)

    def test_editar_con_el_nit_formateado_no_lo_cambia(self):
        proveedor = crear_proveedor(nit="900123456")
        self.client.force_login(self.administrador)
        url = reverse("proveedores:editar", args=[proveedor.pk])
        self.assertEqual(self.client.get(url).context["formulario"].initial["nit"], "900.123.456-8")
        datos = {**self._datos(nit="900.123.456-8"), "razon_social": "Nombre Nuevo Ficticio", "motivo": MOTIVO}
        self.assertRedirects(self.client.post(url, datos), reverse("proveedores:detalle", args=[proveedor.pk]))
        registro = RegistroBitacora.objects.get(accion="proveedor.modificado")
        self.assertEqual(set(registro.valor_nuevo), {"razon_social"})

    def test_busqueda_por_nit_en_cualquier_formato_y_por_nombre(self):
        crear_proveedor(nit="900123456", razon_social="Droguería Ficticia")
        crear_proveedor(nit="811222333", razon_social="Papelería Inventada")
        self.client.force_login(self.administrador)
        for texto in ("900.123.456-8", "900 123", "123456", "droguería"):
            with self.subTest(texto=texto):
                respuesta = self.client.get(reverse("proveedores:lista"), {"q": texto})
                self.assertContains(respuesta, "Droguería Ficticia")
                self.assertNotContains(respuesta, "Papelería Inventada")

    @staticmethod
    def _datos(**cambios):
        datos = {
            "nit": NIT_FICTICIO,
            "razon_social": "Suministros Ficticios S.A.S.",
            "tipo_persona": Proveedor.TipoPersona.JURIDICA,
            "contacto_nombre": "Contacto Ficticio",
            "contacto_correo": "contacto@ejemplo.test",
            "contacto_telefono": "601 555 0100",
            "direccion": "Calle Ficticia 1 # 2-3",
        }
        datos.update(cambios)
        return datos
