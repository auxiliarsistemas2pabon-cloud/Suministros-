from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase

from areas.models import Area


class AreaTests(TestCase):
    def test_normaliza_nombre_y_codigo(self):
        area = Area.objects.create(nombre="  Unidad   de Cuidados ", codigo_area=" uci ")
        self.assertEqual(area.nombre, "Unidad de Cuidados")
        self.assertEqual(area.codigo_area, "UCI")
        self.assertTrue(area.activa)
        self.assertEqual(str(area), "Unidad de Cuidados (UCI)")

    def test_nombre_unico_sin_distinguir_mayusculas(self):
        Area.objects.create(nombre="Farmacia", codigo_area="FAR")
        area = Area(nombre="FARMACIA", codigo_area="FAR2")
        with self.assertRaises(ValidationError):
            area.full_clean()

    def test_codigo_unico_sin_distinguir_mayusculas(self):
        Area.objects.create(nombre="Farmacia", codigo_area="FAR")
        area = Area(nombre="Farmacia Central", codigo_area="far")
        with self.assertRaises(ValidationError) as contexto:
            area.full_clean()
        self.assertIn("codigo_area", contexto.exception.message_dict)

    def test_base_de_datos_exige_codigo_en_mayusculas(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Area.objects.bulk_create([Area(nombre="Bodega", codigo_area="far")])

    def test_base_de_datos_rechaza_nombre_repetido_con_otras_mayusculas(self):
        Area.objects.create(nombre="Farmacia", codigo_area="FAR")
        with self.assertRaises(IntegrityError), transaction.atomic():
            Area.objects.bulk_create([Area(nombre="FARMACIA", codigo_area="FAR2")])
