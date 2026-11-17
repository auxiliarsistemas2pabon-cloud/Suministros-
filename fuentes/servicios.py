"""Carga institucional idempotente: fuentes, histórico, matrices y cortes reales."""
import csv
import json
from decimal import Decimal
from hashlib import sha256
from io import BytesIO, StringIO
from pathlib import Path
import re

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Max

from areas.models import Area
from bitacora.servicios import guardar_con_bitacora, registrar
from compras.models import ContadorOrdenCompra, CriterioElegible, TipoOrigen, TipoPoliza, VersionCriterios
from fuentes.lectura import compras_historicas, elegibles_historicos, leer_libro
from fuentes.models import CompraHistorica, ElegibleHistorico, FormatoInstitucional, SerieArea
from proveedores.models import VersionMatriz
from proveedores.servicios import _exigir_admin, _exigir_motivo, cargar_fr14

TITULOS = {"11": "Proyección anual de compras", "14": "Requisitos de selección de proveedores", "20": "Lista de elegibles",
           "21": "Orden de compra de insumos y servicios", "27": "Seguimiento de compras", "28": "Ficha de cotización"}


def preparar(directorio, corte):
    fuentes = {}
    for path in sorted(Path(directorio).glob("*.xlsx")):
        codigo = re.match(r"FR-GDS-(11|14|20|21|27|28)\b", path.name)
        if not codigo:
            continue
        numero = codigo[1]
        if numero in fuentes:
            raise ValidationError(f"Hay más de un archivo para FR-GDS-{numero}. Seleccione una sola versión.")
        contenido = path.read_bytes()
        fuentes[numero] = {"path": path, "sha": sha256(contenido).hexdigest(), "bytes": contenido, "hojas": leer_libro(path)}
    if set(fuentes) != set(TITULOS):
        raise ValidationError("Se requieren los seis formatos FR-GDS-11, 14, 20, 21, 27 y 28.")
    hojas = {s["nombre"]: s["celdas"] for s in fuentes["27"]["hojas"]}
    codigos = set()
    for serie in corte["series"]:
        codigo = serie["code"]
        if codigo in codigos or len(codigo) > 20:
            raise ValidationError("El corte tiene una serie repetida o un código demasiado largo.")
        codigos.add(codigo)
        origen = serie["source"]
        valor = hojas.get(origen["sheet"], {}).get(origen["cell"])
        if valor is None or str(valor).strip() != str(origen["raw"]).strip() or not re.search(r"(?<!\d)0*" + str(serie["last"]) + r"(?!\d)", valor):
            raise ValidationError(f"El corte de {codigo} no coincide con su celda de origen.")
        if type(serie["last"]) is not int or serie["last"] < 0 or not 0 <= serie["digits"] <= 20:
            raise ValidationError("El corte contiene un número o una longitud inválidos.")
    return fuentes


def _matriz(fr14, actor, motivo):
    version = VersionMatriz.objects.filter(notas__contains=fr14.sha256).first()
    if version:
        return version
    numero = (VersionMatriz.objects.aggregate(n=Max("numero"))["n"] or 0) + 1
    version = VersionMatriz.objects.create(numero=numero, notas=f"Fuente institucional FR-GDS-14 SHA-256 {fr14.sha256}. Encabezado v04 y control de cambios v05: confirmar versión institucional antes de publicar.")
    hoja = next((s["celdas"] for s in fr14.contenido if s["nombre"] == "M_pesos"), None)
    if hoja is None:
        raise ValidationError("No se encontró la tabla de pesos del FR-GDS-14.")
    texto = StringIO(newline="")
    escritor = csv.writer(texto)
    escritor.writerow(["grupo", "numero", "texto", "categoria", "peso"])
    for numero in range(1, 27):
        requisito = hoja.get(f"A{numero+1}", "").strip()
        if not requisito:
            raise ValidationError(f"Falta el requisito {numero} en el formato original.")
        grupo = "calidad" if numero <= 18 else "ambiental" if numero <= 21 else "sgsst"
        for columna in "BCDEFGHIJKL":
            categoria = " ".join(hoja.get(f"{columna}1", "").split())
            peso = hoja.get(f"{columna}{numero+1}", "")
            if not categoria or peso not in {"1", "2", "1.0", "2.0"}:
                raise ValidationError("La tabla oficial contiene una categoría o un peso sin resolver.")
            escritor.writerow([grupo, numero, requisito, categoria, int(float(peso))])
    cargar_fr14(BytesIO(texto.getvalue().encode("utf-8")), actor=actor, motivo=motivo, version=version)
    return version


def _criterios(fr20, actor, motivo):
    version = VersionCriterios.objects.filter(notas__contains=fr20.sha256).first()
    if version:
        return version
    celdas = fr20.contenido[0]["celdas"]
    pesos = [Decimal(celdas[f"{col}6"]) * 100 for col in "FGHI"]
    if sum(pesos) != 100:
        raise ValidationError("Los pesos del FR-GDS-20 no suman 100 %.")
    numero = (VersionCriterios.objects.aggregate(n=Max("numero"))["n"] or 0) + 1
    version = VersionCriterios.objects.create(numero=numero, notas=f"Criterios del archivo institucional SHA-256 {fr20.sha256}; revisión y publicación por administración.")
    for orden, (nombre, peso) in enumerate(zip(["Criterios administrativos", "Precio", "Valor agregado", "Certificaciones"], pesos), 1):
        criterio = CriterioElegible(version=version, orden=orden, nombre=nombre, peso=peso)
        criterio.full_clean()
        guardar_con_bitacora(criterio, ["nombre", "peso", "orden"], actor=actor, motivo=motivo,
                            accion_crear="criterio.institucional_cargado", accion_modificar="criterio.institucional_modificado")
    registrar("criterios.institucionales_cargados", actor=actor, objeto=version, motivo=motivo)
    return version


def reglas_desde_formulas(fr14, fr20, *, actor, motivo):
    """Reconoce fórmulas concretas de las fuentes; conserva pendiente la aprobación institucional."""
    from parametros.catalogo import DEFINICIONES, REGLAS_ELEGIBLES, REGLAS_FR14
    from parametros.models import Parametro
    from parametros.servicios import cambiar_valor
    cambios = {}
    evaluacion = next((h for h in fr14.contenido if h["nombre"] == "Evaluacion"), {})
    formulas = {k: v.upper().replace("$", "").replace(" ", "") for k, v in evaluacion.get("formulas", {}).items()}
    umbrales = re.fullmatch(r'IF\(I13<(\d+(?:\.\d+)?)%,1,IF\(I13<(\d+(?:\.\d+)?)%,3,5\)\)', formulas.get("J13", ""))
    if umbrales and formulas.get("F13") == 'IF(D13="SI",E13,0)' and formulas.get("G13") == 'IF(D13="N/A",0,E13)':
        cambios[REGLAS_FR14] = {"si": "1", "no": "0", "excluir_na": True, "umbral3": umbrales[1], "umbral5": umbrales[2], "pendiente": True}
    formula20 = fr20.contenido[0].get("formulas", {}).get("H9", "").upper().replace("$", "").replace(" ", "")
    if formula20 == "F9*F6/5%":
        cambios[REGLAS_ELEGIBLES] = {"metodo": "escalado", "escala": ["5", "3", "1"], "pendiente": True}
    for clave, datos in cambios.items():
        definicion = DEFINICIONES[clave]
        parametro, _ = Parametro.objects.get_or_create(clave=clave, defaults={"nombre": definicion.nombre,
            "tipo": definicion.tipo, "valor": definicion.valor_por_defecto, "valor_por_defecto": definicion.valor_por_defecto})
        actual = json.loads(parametro.valor)
        if actual == datos:
            continue
        if actual != json.loads(definicion.valor_por_defecto):
            raise ValidationError("Las reglas de cálculo ya fueron personalizadas. Revise la fuente antes de cambiarlas.")
        cambiar_valor(parametro, json.dumps(datos), actor=actor,
                      motivo=motivo + " Fórmulas del Excel original; se conserva pendiente la validación institucional.")
    return sorted(cambios)


@transaction.atomic
def cargar(fuentes, corte, *, actor, motivo):
    _exigir_admin(actor)
    _exigir_motivo(motivo)
    resultado = {"formatos_nuevos": 0, "compras_historicas_nuevas": 0, "elegibles_historicos_nuevos": 0, "areas_nuevas": 0, "series_nuevas": 0}
    registros = {}
    for numero, datos in fuentes.items():
        ruta = Path("formatos_institucionales") / f"{datos['sha']}.xlsx"
        destino = Path(settings.MEDIA_ROOT) / ruta
        destino.parent.mkdir(parents=True, exist_ok=True)
        if destino.exists() and sha256(destino.read_bytes()).hexdigest() != datos["sha"]:
            raise ValidationError("La copia privada de un formato tiene una huella distinta.")
        if not destino.exists():
            destino.write_bytes(datos["bytes"])
        fuente, nueva = FormatoInstitucional.objects.get_or_create(sha256=datos["sha"], defaults={
            "codigo": f"FR-GDS-{numero}", "titulo": TITULOS[numero], "nombre_original": datos["path"].name,
            "archivo": ruta.as_posix(), "contenido": datos["hojas"], "resumen": {"hojas": len(datos["hojas"])}})
        registros[numero] = fuente
        if not nueva:
            continue
        resultado["formatos_nuevos"] += 1
        if numero == "27":
            filas = [CompraHistorica(fuente=fuente, **f) for f in compras_historicas(datos["hojas"])]
            CompraHistorica.objects.bulk_create(filas, batch_size=300)
            resultado["compras_historicas_nuevas"] += len(filas)
        if numero == "20":
            filas = [ElegibleHistorico(fuente=fuente, **f) for f in elegibles_historicos(datos["hojas"])]
            ElegibleHistorico.objects.bulk_create(filas, batch_size=300)
            resultado["elegibles_historicos_nuevos"] += len(filas)
        registrar("fuente.institucional_cargada", actor=actor, objeto=fuente, motivo=motivo,
                  nuevo={"sha256": fuente.sha256, "nombre": fuente.nombre_original, "hojas": len(datos["hojas"])})
    for datos in corte["series"]:
        area = Area.objects.filter(codigo_area=datos["code"]).first()
        if area is None:
            area = Area(nombre=datos["name"], codigo_area=datos["code"])
            area.full_clean()
            guardar_con_bitacora(area, ["nombre", "codigo_area", "activa"], actor=actor, motivo=motivo,
                                accion_crear="area.cargada_desde_fuente", accion_modificar="area.modificada")
            resultado["areas_nuevas"] += 1
        serie = SerieArea.objects.select_for_update().filter(codigo=datos["code"]).first()
        if serie and serie.area_id != area.pk:
            raise ValidationError("La serie ya pertenece a otra área; no se reasignó automáticamente.")
        nueva = serie is None
        serie = serie or SerieArea(area=area, codigo=datos["code"], ultimo_historico=datos["last"])
        campos = {"ultimo_historico": max(serie.ultimo_historico, datos["last"]), "fuente": registros["27"],
                  "sin_prefijo": datos["code"] == "SIN PREFIJO", "longitud": max(1, datos["digits"]),
                  "celda_origen": f"'{datos['source']['sheet']}'!{datos['source']['cell']}",
                  "referencia_original": datos["source"]["raw"], "observaciones": datos["note"]}
        if nueva or any(getattr(serie, campo) != valor for campo, valor in campos.items()):
            for campo, valor in campos.items():
                setattr(serie, campo, valor)
            serie.full_clean()
            guardar_con_bitacora(serie, list(campos), actor=actor, motivo=motivo,
                                accion_crear="serie.institucional_cargada", accion_modificar="serie.corte_actualizado")
        contador, creado = ContadorOrdenCompra.objects.get_or_create(clave=serie.clave_contador, defaults={"ultimo": serie.ultimo_historico})
        if contador.ultimo < serie.ultimo_historico:
            contador.ultimo = serie.ultimo_historico
            guardar_con_bitacora(contador, ["ultimo"], actor=actor, motivo=motivo,
                                accion_crear="orden.contador_creado", accion_modificar="orden.corte_actualizado")
        elif creado:
            registrar("orden.corte_inicial_cargado", actor=actor, objeto=contador, nuevo={"ultimo": contador.ultimo}, motivo=motivo)
        resultado["series_nuevas"] += int(nueva)
    resultado["matriz_fr14"] = _matriz(registros["14"], actor, motivo).numero
    resultado["version_criterios_fr20"] = _criterios(registros["20"], actor, motivo).numero
    resultado["reglas_cargadas_desde_formulas"] = reglas_desde_formulas(registros["14"], registros["20"], actor=actor, motivo=motivo)
    # Opciones explícitas del formato contractual; no se exige una póliza por el solo hecho de cargar su tipo.
    hoja28 = registros["28"].contenido[0]["celdas"]
    resultado["tipos_poliza_creados"] = 0
    for posicion, fila in enumerate(range(47, 53), 1):
        nombre = " ".join(hoja28.get(f"A{fila}", "").split())
        if nombre and not TipoPoliza.objects.filter(nombre__iexact=nombre).exists():
            tipo = TipoPoliza(nombre=nombre, orden=posicion)
            tipo.full_clean()
            guardar_con_bitacora(tipo, ["nombre", "orden", "activo"], actor=actor, motivo=motivo,
                                accion_crear="poliza.tipo_institucional_cargado", accion_modificar="poliza.tipo_modificado")
            resultado["tipos_poliza_creados"] += 1
    for nombre in ["Proyección anual", "Necesidad no prevista"]:
        if not TipoOrigen.objects.filter(nombre__iexact=nombre).exists():
            origen = TipoOrigen(nombre=nombre)
            origen.full_clean()
            guardar_con_bitacora(origen, ["nombre", "activo"], actor=actor, motivo=motivo,
                                accion_crear="origen.institucional_cargado", accion_modificar="origen.modificado")
    return resultado
