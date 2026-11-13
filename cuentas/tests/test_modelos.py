from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase

from cuentas.forms import FormularioCreacionUsuario
from cuentas.models import Rol, Usuario
from cuentas.tests.utilidades import CLAVE, crear_area, crear_usuario


class CrearUsuarioTests(TestCase):
    def setUp(self):
        self.area = crear_area()

    def test_crear_usuario(self):
        usuario = Usuario.objects.create_user(
            correo="  Ana.Perez@Ejemplo.TEST ",
            password=CLAVE,
            nombre="Ana Pérez",
            rol=Rol.COORDINADOR,
            area=self.area,
        )
        self.assertEqual(usuario.correo, "ana.perez@ejemplo.test")
        self.assertTrue(usuario.check_password(CLAVE))
        self.assertTrue(usuario.activo)
        self.assertTrue(usuario.is_active)
        self.assertFalse(usuario.is_staff)
        self.assertFalse(usuario.is_superuser)
        self.assertFalse(usuario.debe_cambiar_clave)
        self.assertIsNotNone(usuario.fecha_creacion)
        self.assertEqual(usuario.get_full_name(), "Ana Pérez")

    def test_crear_superusuario_queda_desarrollador(self):
        usuario = Usuario.objects.create_superuser(
            correo="Raiz@Ejemplo.test", password=CLAVE, nombre="Soporte Técnico"
        )
        self.assertEqual(usuario.correo, "raiz@ejemplo.test")
        self.assertEqual(usuario.rol, Rol.DESARROLLADOR)
        self.assertTrue(usuario.is_staff)
        self.assertTrue(usuario.is_superuser)
        self.assertTrue(usuario.es_admin)

    def test_superusuario_con_otro_rol_rechazado(self):
        with self.assertRaises(ValueError):
            Usuario.objects.create_superuser(
                correo="raiz@ejemplo.test", password=CLAVE, nombre="X", rol=Rol.ADMINISTRADOR
            )

    def test_correo_obligatorio(self):
        with self.assertRaises(ValueError):
            Usuario.objects.create_user(correo="", password=CLAVE, nombre="X", rol=Rol.ADMINISTRADOR)

    def test_sin_clave_queda_inutilizable(self):
        usuario = Usuario.objects.create_user(
            correo="sinclave@ejemplo.test", nombre="Sin Clave", rol=Rol.ADMINISTRADOR
        )
        self.assertFalse(usuario.has_usable_password())

    def test_ingreso_por_correo_sin_distinguir_mayusculas(self):
        usuario = crear_usuario(Rol.ADMINISTRADOR, correo="admin@ejemplo.test")
        self.assertEqual(Usuario.objects.get_by_natural_key("ADMIN@Ejemplo.Test"), usuario)

    def test_is_active_refleja_activo(self):
        usuario = crear_usuario(Rol.ADMINISTRADOR)
        usuario.activo = False
        self.assertFalse(usuario.is_active)
        usuario.is_active = True
        self.assertTrue(usuario.activo)


class CorreoDuplicadoTests(TestCase):
    def setUp(self):
        crear_usuario(Rol.ADMINISTRADOR, correo="maria@ejemplo.test")

    def test_create_user_rechaza_duplicado_con_otras_mayusculas(self):
        with self.assertRaises(ValidationError) as contexto:
            crear_usuario(Rol.DESARROLLADOR, correo="MARIA@Ejemplo.Test")
        self.assertIn("correo", contexto.exception.message_dict)

    def test_formulario_rechaza_duplicado_con_otras_mayusculas(self):
        formulario = FormularioCreacionUsuario(
            data={
                "correo": "Maria@EJEMPLO.test",
                "nombre": "María Duplicada",
                "rol": Rol.ADMINISTRADOR,
                "password1": CLAVE,
                "password2": CLAVE,
            }
        )
        self.assertFalse(formulario.is_valid())
        self.assertEqual(formulario.errors["correo"], ["Ya existe un usuario con este correo."])
        # El error se muestra una sola vez, junto al campo.
        self.assertNotIn("__all__", formulario.errors)

    def test_base_de_datos_rechaza_duplicado_aunque_se_salte_save(self):
        otro = crear_usuario(Rol.DESARROLLADOR, correo="otro@ejemplo.test")
        with self.assertRaises(IntegrityError), transaction.atomic():
            Usuario.objects.filter(pk=otro.pk).update(correo="maria@ejemplo.test")

    def test_base_de_datos_exige_correo_en_minusculas(self):
        otro = crear_usuario(Rol.DESARROLLADOR, correo="otro@ejemplo.test")
        for correo in ("MARIA@ejemplo.test", "Otro@Ejemplo.test"):
            with self.subTest(correo=correo), self.assertRaises(IntegrityError), transaction.atomic():
                Usuario.objects.filter(pk=otro.pk).update(correo=correo)


class ReglasDeRolTests(TestCase):
    def setUp(self):
        self.area = crear_area()

    def test_coordinador_sin_area_invalido(self):
        with self.assertRaises(ValidationError) as contexto:
            Usuario.objects.create_user(
                correo="coordinador@ejemplo.test", password=CLAVE, nombre="C", rol=Rol.COORDINADOR
            )
        self.assertIn("area", contexto.exception.message_dict)

    def test_coordinador_sin_area_rechazado_por_la_base(self):
        coordinador = crear_usuario(Rol.COORDINADOR, area=self.area)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Usuario.objects.filter(pk=coordinador.pk).update(area=None)

    def test_proveedor_con_area_invalido(self):
        with self.assertRaises(ValidationError) as contexto:
            crear_usuario(Rol.PROVEEDOR, area=self.area)
        self.assertIn("area", contexto.exception.message_dict)

    def test_proveedor_con_area_rechazado_por_la_base(self):
        proveedor = crear_usuario(Rol.PROVEEDOR)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Usuario.objects.filter(pk=proveedor.pk).update(area=self.area)

    def test_proveedor_sin_area_valido(self):
        self.assertIsNone(crear_usuario(Rol.PROVEEDOR).area)

    def test_administrador_puede_tener_o_no_area(self):
        crear_usuario(Rol.ADMINISTRADOR, correo="a1@ejemplo.test")
        crear_usuario(Rol.ADMINISTRADOR, correo="a2@ejemplo.test", area=self.area)

    def test_solo_desarrolladores_pueden_ser_staff_o_superusuario(self):
        for rol in (Rol.COORDINADOR, Rol.PROVEEDOR, Rol.ADMINISTRADOR):
            for campo in ("is_staff", "is_superuser"):
                with self.subTest(rol=rol, campo=campo), self.assertRaises(ValidationError) as contexto:
                    crear_usuario(rol, correo=f"{campo}-{rol}@ejemplo.test", **{campo: True})
                self.assertIn("rol", contexto.exception.message_dict)
        crear_usuario(Rol.DESARROLLADOR, is_staff=True)

    def test_staff_de_otro_rol_rechazado_por_la_base(self):
        administrador = crear_usuario(Rol.ADMINISTRADOR)
        for campo in ("is_staff", "is_superuser"):
            with self.subTest(campo=campo), self.assertRaises(IntegrityError), transaction.atomic():
                Usuario.objects.filter(pk=administrador.pk).update(**{campo: True})

    def test_rol_invalido(self):
        with self.assertRaises(ValidationError) as contexto:
            crear_usuario("jefe", correo="jefe@ejemplo.test")
        self.assertIn("rol", contexto.exception.message_dict)

    def test_area_con_usuarios_no_se_puede_borrar(self):
        from django.db.models import ProtectedError

        crear_usuario(Rol.COORDINADOR, area=self.area)
        with self.assertRaises(ProtectedError):
            self.area.delete()
