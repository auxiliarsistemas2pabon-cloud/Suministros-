"""Consolidado de la proyección anual por año y área (GDS-PRY-06).

Todo se calcula con agregaciones de PostgreSQL y `Decimal`:

- Proyectado (valores aprobados o diligenciados): cantidades por mes, total anual y costo.
- Cantidad autorizada: la registrada al aprobar.
- Ajustado (vigente): el valor del último ajuste de cada campo o, si no tiene ajustes, el de
  la línea. Da la cantidad ajustada (autorizada vigente), el total anual ajustado y el costo
  ajustado (meses vigentes × precio vigente).

`consulta` es siempre un QuerySet de ProyeccionArea ya filtrado (ver servicios.filtrar_proyecciones).
"""

from decimal import Decimal

from django.db.models import (
    BigIntegerField,
    Count,
    DecimalField,
    ExpressionWrapper,
    F,
    Func,
    OuterRef,
    Subquery,
    Sum,
    TextField,
)
from django.db.models.functions import Cast, Coalesce

from proyecciones.models import CAMPOS_AJUSTABLES, CAMPOS_CANTIDADES_MENSUALES, Ajuste, Linea, ProyeccionArea

DECIMAL_COSTO = DecimalField(max_digits=30, decimal_places=2)
DECIMAL_PRECIO = DecimalField(max_digits=14, decimal_places=2)

# Nombre de cada valor agregado, en el orden en que se muestran.
CLAVES_MESES = [f"mes_{numero}" for numero in range(1, 13)]
CLAVES_TOTALES = [
    "numero_lineas",
    *CLAVES_MESES,
    "total_anual",
    "costo",
    "cantidad_autorizada",
    "cantidad_ajustada",
    "total_ajustado",
    "costo_ajustado",
]
# Valores que quedan en cero si no hay líneas; los demás quedan en None («—»).
CLAVES_CON_CERO = {"numero_lineas", *CLAVES_MESES, "total_anual", "costo", "total_ajustado", "costo_ajustado"}


class TextoJson(Func):
    """Valor escalar de un campo JSON como texto (`valor #>> '{}'`), para convertirlo después."""

    template = "(%(expressions)s #>> '{}')"
    output_field = TextField()

    def as_sqlite(self, compiler, connection, **extra_context):
        return self.as_sql(compiler, connection, template="JSON_EXTRACT(%(expressions)s, '$')", **extra_context)


def _vigente(campo):
    """Valor vigente de un campo de la línea: último ajuste de ese campo o el valor de la línea."""
    tipo = DECIMAL_PRECIO if campo == "precio_estimado" else BigIntegerField()
    ultimo = (
        Ajuste.objects.filter(linea=OuterRef("pk"), campo=campo)
        .order_by("-fecha", "-id")
        .annotate(texto=TextoJson("valor_nuevo"))
        .values("texto")[:1]
    )
    return Coalesce(Cast(Subquery(ultimo), tipo), Cast(F(campo), tipo), output_field=tipo)


def _suma_meses(prefijo=""):
    primero, *resto = CAMPOS_CANTIDADES_MENSUALES
    expresion = Cast(F(f"{prefijo}{primero}"), BigIntegerField())
    for campo in resto:
        expresion = expresion + F(f"{prefijo}{campo}")
    return expresion


def lineas_con_vigentes(consulta):
    """Líneas de las proyecciones del filtro, con sus valores vigentes anotados (`v_<campo>`)."""
    lineas = Linea.objects.filter(proyeccion__in=consulta.values("pk"))
    return lineas.annotate(**{f"v_{campo}": _vigente(campo) for campo in CAMPOS_AJUSTABLES}).annotate(
        v_total=_suma_meses("v_"),
        total=_suma_meses(),
        costo=ExpressionWrapper(_suma_meses() * F("precio_estimado"), output_field=DECIMAL_COSTO),
        v_costo=ExpressionWrapper(_suma_meses("v_") * F("v_precio_estimado"), output_field=DECIMAL_COSTO),
    )


def _agregados():
    """Agregados con alias `agr_<clave>` (un alias no puede llamarse como un campo del modelo)."""
    agregados = {"numero_lineas": Count("pk")}
    for clave, campo in zip(CLAVES_MESES, CAMPOS_CANTIDADES_MENSUALES):
        agregados[clave] = Sum(campo)
    agregados.update(
        total_anual=Sum("total"),
        costo=Sum("costo", output_field=DECIMAL_COSTO),
        cantidad_autorizada=Sum("cantidad_autorizada"),
        cantidad_ajustada=Sum("v_cantidad_autorizada"),
        total_ajustado=Sum("v_total"),
        costo_ajustado=Sum("v_costo", output_field=DECIMAL_COSTO),
    )
    return {f"agr_{clave}": expresion for clave, expresion in agregados.items()}


def _normalizar(valores):
    """Ceros donde no hay líneas y montos como Decimal con dos decimales."""
    resultado = {}
    for clave in CLAVES_TOTALES:
        valor = valores.get(f"agr_{clave}")
        if valor is None and clave in CLAVES_CON_CERO:
            valor = 0
        if clave in ("costo", "costo_ajustado"):
            valor = Decimal(valor).quantize(Decimal("0.01"))
        elif valor is not None:
            valor = int(valor)
        resultado[clave] = valor
    return resultado


def filas_por_area(consulta):
    """Una fila por proyección (año y área) del filtro, también las que no tienen líneas."""
    agregados = {
        fila.pop("proyeccion"): fila
        for fila in lineas_con_vigentes(consulta).values("proyeccion").annotate(**_agregados()).order_by()
    }
    filas = []
    for proyeccion in consulta.select_related("periodo", "area").order_by("-periodo__anio", "area__nombre"):
        fila = _normalizar(agregados.get(proyeccion.pk, {}))
        fila.update(
            proyeccion=proyeccion,
            anio=proyeccion.periodo.anio,
            area=proyeccion.area.nombre,
            codigo_area=proyeccion.area.codigo_area,
            estado=proyeccion.get_estado_display(),
            meses=[fila[clave] for clave in CLAVES_MESES],
        )
        filas.append(fila)
    return filas


def totales(consulta):
    """Los mismos valores de `filas_por_area`, sumados para todo el filtro."""
    fila = _normalizar(lineas_con_vigentes(consulta).aggregate(**_agregados()))
    fila["meses"] = [fila[clave] for clave in CLAVES_MESES]
    return fila


def lineas_de(proyeccion):
    """Detalle de las líneas de una proyección con valores proyectados y vigentes (para el Excel)."""
    return (
        lineas_con_vigentes(ProyeccionArea.objects.filter(pk=proyeccion.pk))
        .select_related("unidad")
        .order_by("producto_servicio", "id")
    )
