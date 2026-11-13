"""Parámetros conocidos por el sistema y su valor por defecto documentado.

Si un parámetro todavía no existe en la base (o se consulta antes de migrar), el servicio
`parametros.servicios.obtener` usa el valor por defecto de aquí. La migración de datos
0002 crea los registros con estos mismos valores.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
import json
import re
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError


@dataclass(frozen=True)
class DefinicionParametro:
    clave: str
    nombre: str
    tipo: str
    valor_por_defecto: str
    descripcion: str
    decision: str = ""
    minimo: int | None = None  # Solo para tipos numéricos.
    # Valida (y normaliza) el valor ya convertido; lanza ValidationError si no es aceptable.
    validador: Callable[[Any], Any] | None = None


# Roles que pueden aprobar proveedores (D-03): solo los de administración tienen acceso
# a /proveedores/, así que no tiene sentido asignar coordinadores ni proveedores.
ROLES_ADMIN_TEXTO = ("administrador", "desarrollador")


def lista_de_roles(texto):
    """«administrador, Desarrollador» → ["administrador", "desarrollador"] (sin repetidos)."""
    return list(dict.fromkeys(parte.strip().lower() for parte in str(texto or "").split(",") if parte.strip()))


def validar_roles_aprobadores(texto):
    roles = lista_de_roles(texto)
    if not roles:
        raise ValidationError({"valor": "Indique al menos un rol."})
    desconocidos = [rol for rol in roles if rol not in ROLES_ADMIN_TEXTO]
    if desconocidos:
        raise ValidationError(
            {
                "valor": f"Roles no válidos: {', '.join(desconocidos)}. "
                f"Use uno o ambos de: {', '.join(ROLES_ADMIN_TEXTO)}, separados por coma."
            }
        )
    return ",".join(roles)


PERMITIR_DEVOLUCION = "proyeccion.permitir_devolucion"
APROBACIONES_REQUERIDAS = "proyeccion.aprobaciones_requeridas"
ROLES_APROBADORES_PROVEEDOR = "proveedor.roles_aprobadores"
DIAS_ALERTA_VENCIMIENTO = "proveedor.dias_alerta_vencimiento"
ACTIVAR_REGISTRO_PORTAL = "portal.activar_cuenta_al_registrar"
CONSERVAR_PDF_DESCARTADO = "proveedor.conservar_pdf_descartado"
REGLAS_FR14 = "evaluacion.reglas_calculo"
BLOQUEAR_SI_VENCIDO = "evaluacion.bloquear_si_documento_vencido"
REGLAS_FR14_DEFECTO = '{"si":"1","no":"0","excluir_na":true,"umbral3":"60","umbral5":"80","pendiente":true}'
REGLAS_ELEGIBLES = "elegibles.reglas_calculo"
CONTROL_DOCUMENTAL_ELEGIBLES = "elegibles.control_documental"
MESES_EVALUACION_ELEGIBLES = "elegibles.antiguedad_evaluacion_meses"
MAX_OFERENTES_COTIZACION = "cotizacion.max_oferentes"
MAX_LINEAS_COTIZACION = "cotizacion.max_lineas"
DECIMALES_OFERTA = "cotizacion.decimales_importes"
REDONDEO_OFERTA = "cotizacion.modo_redondeo"
MIN_JUSTIFICACION_UNICO = "cotizacion.proveedor_unico_min_caracteres"
EVIDENCIA_UNICO_OBLIGATORIA = "cotizacion.proveedor_unico_evidencia_obligatoria"
MODALIDAD_ADJUDICACION = "cotizacion.modalidad_adjudicacion"
APROBACIONES_COTIZACION = "cotizacion.aprobaciones_requeridas"
ROLES_DECISION_COTIZACION = "cotizacion.roles_aprobadores"
CONTROL_VERIFICACIONES = "cotizacion.control_verificaciones"
CAMPOS_CONTRATO = "contrato.campos_obligatorios"
CAMPOS_POLIZA = "poliza.campos_obligatorios"
EXIGIR_POLIZA = "contrato.exigir_poliza"
PREFIJO_ORDEN = "orden.prefijo_consecutivo"
ANIO_ORDEN = "orden.incluir_anio_consecutivo"
LONGITUD_ORDEN = "orden.longitud_consecutivo"
REINICIO_ORDEN = "orden.reinicio_anual_consecutivo"
ETIQUETA_VALIDEZ_ORDEN = "orden.etiqueta_fecha_validez"
DESCUENTO_ORDEN = "orden.orden_descuento"
NIVEL_REDONDEO_ORDEN = "orden.nivel_redondeo"
DECIMALES_ORDEN = "orden.decimales_importes"
MODO_REDONDEO_ORDEN = "orden.modo_redondeo"
AUTOAPROBAR_ORDEN = "orden.permitir_aprobar_propia"
CLIENTE_ORDEN = "orden.cliente_nombre"
NIT_CLIENTE_ORDEN = "orden.cliente_nit"
EXCESO_RECEPCION = "orden.permitir_exceso_recepcion"
COORDINADOR_RECEPCION = "orden.coordinador_puede_recibir"
AUTO_SEGUIMIENTO = "seguimiento.crear_al_emitir"
REABRIR_SEGUIMIENTO = "seguimiento.permitir_reapertura"
CIERRE_CON_SALDO = "seguimiento.cierre_con_saldo"
DIAS_SEGUIMIENTO = "seguimiento.dias_alerta"
CONSULTA_COORDINADOR_SEGUIMIENTO = "seguimiento.coordinador_puede_consultar"


def validar_cierre_saldo(valor):
    valor = valor.strip().lower()
    if valor not in ("advertir", "bloquear"):
        raise ValidationError({"valor": "Use advertir o bloquear."})
    return valor


def validar_orden_descuento(valor):
    valor = valor.strip().lower()
    if valor not in ("antes_impuesto", "despues_impuesto"):
        raise ValidationError({"valor": "Use antes_impuesto o despues_impuesto."})
    return valor


def validar_nivel_redondeo_orden(valor):
    valor = valor.strip().lower()
    if valor not in ("linea", "total"):
        raise ValidationError({"valor": "Use linea o total."})
    return valor


def validar_prefijo_orden(valor):
    valor = valor.strip().upper()
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9_-]{0,19}", valor):
        raise ValidationError({"valor": "Use de 1 a 20 letras, números, guiones o guiones bajos; comience por letra o número."})
    return valor


def validar_longitud_orden(valor):
    if type(valor) is not int or not 1 <= valor <= 20:
        raise ValidationError({"valor": "Use una longitud mínima de 1 a 20 dígitos."})
    return valor


def validar_etiqueta_validez(valor):
    valor = " ".join(valor.split())
    if not 1 <= len(valor) <= 80:
        raise ValidationError({"valor": "Escriba una etiqueta de 1 a 80 caracteres."})
    return valor
CONTRATO_DEFECTO = '{"numero":true,"supervisor":true,"cargo":true,"fecha_inicio":true,"fecha_fin":true,"forma_pago":true,"valor":true,"pdf":false}'
POLIZA_DEFECTO = '{"tipo":true,"aseguradora":true,"numero":true,"valor_asegurado":true,"vigencia_desde":true,"vigencia_hasta":true,"pdf":true}'


def _validar_obligatoriedad(texto, campos):
    try:
        datos = json.loads(texto)
        if not isinstance(datos, dict) or set(datos) != set(campos) or any(type(v) is not bool for v in datos.values()):
            raise ValueError
        return json.dumps(datos, separators=(",", ":"))
    except (ValueError, TypeError):
        raise ValidationError({"valor": "Indique un objeto JSON con todos los campos conocidos y valores true/false: " + ", ".join(campos)}) from None


def validar_campos_contrato(texto):
    return _validar_obligatoriedad(texto, ("numero", "supervisor", "cargo", "fecha_inicio", "fecha_fin", "forma_pago", "valor", "pdf"))


def validar_campos_poliza(texto):
    return _validar_obligatoriedad(texto, ("tipo", "aseguradora", "numero", "valor_asegurado", "vigencia_desde", "vigencia_hasta", "pdf"))


def validar_modalidad_adjudicacion(valor):
    valor = valor.strip().lower()
    if valor not in ("completa", "lineas"):
        raise ValidationError({"valor": "Use completa o lineas."})
    return valor


def validar_decimales_oferta(valor):
    if type(valor) is not int or valor not in (0, 1, 2):
        raise ValidationError({"valor": "Use 0, 1 o 2 decimales."})
    return valor


def validar_redondeo_oferta(valor):
    valor = valor.strip().upper()
    if valor not in ("ROUND_HALF_UP", "ROUND_HALF_EVEN", "ROUND_DOWN", "ROUND_UP"):
        raise ValidationError({"valor": "Use ROUND_HALF_UP, ROUND_HALF_EVEN, ROUND_DOWN o ROUND_UP."})
    return valor
REGLAS_ELEGIBLES_DEFECTO = '{"metodo":"directo","escala":["5","3","1"],"pendiente":true}'


def validar_control_documental_elegibles(valor):
    valor = valor.strip().lower()
    if valor not in ("advertir", "bloquear"):
        raise ValidationError({"valor": "Use advertir o bloquear."})
    return valor


def validar_reglas_elegibles(texto):
    try:
        datos = json.loads(texto)
        if not isinstance(datos, dict) or set(datos) != {"metodo", "escala", "pendiente"}:
            raise ValueError
        if datos["metodo"] not in ("directo", "escalado") or type(datos["pendiente"]) is not bool:
            raise ValueError
        if not isinstance(datos["escala"], list) or not 2 <= len(datos["escala"]) <= 10:
            raise ValueError
        escala = []
        for dato in datos["escala"]:
            if isinstance(dato, (bool, float)) or not isinstance(dato, (str, int)):
                raise ValueError
            valor = Decimal(str(dato))
            if not valor.is_finite() or not 0 <= valor <= 100 or valor.as_tuple().exponent < -3:
                raise ValueError
            escala.append(valor)
        if len(set(escala)) != len(escala) or max(escala) <= 0:
            raise ValueError
        datos["escala"] = [str(v) for v in sorted(escala, reverse=True)]
        return json.dumps(datos, separators=(",", ":"))
    except (ValueError, TypeError, InvalidOperation):
        raise ValidationError({"valor": 'Indique JSON con metodo directo/escalado, escala de 2 a 10 valores distintos entre 0 y 100 (máximo tres decimales, escritos entre comillas), y pendiente booleano. El máximo debe ser positivo.'}) from None


def validar_reglas_fr14(texto):
    try:
        datos = json.loads(texto)
        if set(datos) != {"si", "no", "excluir_na", "umbral3", "umbral5", "pendiente"}:
            raise ValueError
        for campo in ("si", "no", "umbral3", "umbral5"):
            if isinstance(datos[campo], (bool, float)):
                raise ValueError
            numero = Decimal(str(datos[campo]))
            if not numero.is_finite() or not 0 <= numero <= (1 if campo in ("si", "no") else 100):
                raise ValueError
            datos[campo] = str(numero)
        if Decimal(datos["umbral3"]) >= Decimal(datos["umbral5"]):
            raise ValueError
        if type(datos["excluir_na"]) is not bool or type(datos["pendiente"]) is not bool:
            raise ValueError
        return json.dumps(datos, separators=(",", ":"))
    except (ValueError, TypeError, InvalidOperation):
        raise ValidationError({"valor": 'Indique JSON con si/no entre 0 y 1, excluir_na y pendiente booleanos, y 0 ≤ umbral3 < umbral5 ≤ 100. Use texto decimal entre comillas.'}) from None

DEFINICIONES = {
    AUTO_SEGUIMIENTO: DefinicionParametro(clave=AUTO_SEGUIMIENTO, nombre="Crear seguimiento al emitir orden", tipo="booleano", valor_por_defecto="true", descripcion="Crea un seguimiento por orden en la misma transacción de emisión. Si se desactiva, puede iniciarlo manualmente."),
    REABRIR_SEGUIMIENTO: DefinicionParametro(clave=REABRIR_SEGUIMIENTO, nombre="Permitir reapertura de seguimientos", tipo="booleano", valor_por_defecto="false", decision="D-15", descripcion="Inicialmente deshabilitada; solo administradores, con motivo, registro de reapertura y estado de orden derivado de recepciones."),
    CIERRE_CON_SALDO: DefinicionParametro(clave=CIERRE_CON_SALDO, nombre="Cierre de seguimiento con líneas pendientes", tipo="texto", valor_por_defecto="bloquear", decision="D-15", validador=validar_cierre_saldo, descripcion="Provisional: bloquear si hay saldos sin cierre justificado de línea. advertir permite cierre con observación y conserva saldos visibles."),
    DIAS_SEGUIMIENTO: DefinicionParametro(clave=DIAS_SEGUIMIENTO, nombre="Días de próximos vencimientos de seguimiento", tipo="entero", valor_por_defecto="7", minimo=0, decision="D-15", descripcion="Ventana del panel de próximos hitos. No se precargan plazos SLA reales."),
    CONSULTA_COORDINADOR_SEGUIMIENTO: DefinicionParametro(clave=CONSULTA_COORDINADOR_SEGUIMIENTO, nombre="Coordinadores pueden consultar seguimientos del área", tipo="booleano", valor_por_defecto="false", descripcion="Preparado para habilitación futura. Inicialmente solo administradores; al habilitar, consulta y reportes solo del área propia, sin mutaciones."),
    EXCESO_RECEPCION: DefinicionParametro(clave=EXCESO_RECEPCION, nombre="Permitir autorizar exceso de recepción", tipo="booleano", valor_por_defecto="false", decision="D-14", descripcion="Inicialmente bloqueado. Si se habilita, un administrador debe autorizar expresamente cada movimiento que aumente el exceso y registrar motivo."),
    COORDINADOR_RECEPCION: DefinicionParametro(clave=COORDINADOR_RECEPCION, nombre="Coordinadores pueden recibir en su área", tipo="booleano", valor_por_defecto="false", decision="D-14", descripcion="Elección del usuario: solo administradores y desarrolladores inicialmente. Si se activa, coordinadores activos solo en el área de origen; no autorizan excesos."),
    AUTOAPROBAR_ORDEN: DefinicionParametro(clave=AUTOAPROBAR_ORDEN, nombre="Permitir aprobar la propia orden", tipo="booleano", valor_por_defecto="false", decision="D-12", descripcion="Provisional: No. La aprobación requiere un administrador distinto del elaborador. Se conserva la política al solicitar aprobación."),
    CLIENTE_ORDEN: DefinicionParametro(clave=CLIENTE_ORDEN, nombre="Nombre de la clínica en órdenes", tipo="texto", valor_por_defecto="POR CONFIGURAR", descripcion="Configure la razón social antes de solicitar aprobación. Se conserva en el documento emitido."),
    NIT_CLIENTE_ORDEN: DefinicionParametro(clave=NIT_CLIENTE_ORDEN, nombre="NIT de la clínica en órdenes", tipo="texto", valor_por_defecto="POR CONFIGURAR", descripcion="Configure el NIT antes de solicitar aprobación. No se precargan datos reales."),
    DESCUENTO_ORDEN: DefinicionParametro(
        clave=DESCUENTO_ORDEN, nombre="Descuento antes o después de impuesto en orden", tipo="texto", valor_por_defecto="antes_impuesto", decision="D-11",
        validador=validar_orden_descuento, descripcion="Provisional, pendiente de validar con financiera. antes_impuesto calcula impuesto sobre bruto menos descuento; despues_impuesto calcula sobre bruto. Se adopta explícitamente en borrador y se conserva al emitir.",
    ),
    NIVEL_REDONDEO_ORDEN: DefinicionParametro(
        clave=NIVEL_REDONDEO_ORDEN, nombre="Nivel de redondeo de orden", tipo="texto", valor_por_defecto="linea", decision="D-11",
        validador=validar_nivel_redondeo_orden, descripcion="Provisional: linea redondea cada bruto, descuento e impuesto. total redondea sus sumas y distribuye diferencias por residuos, con desempate por posición; nunca asigna descuento mayor al bruto. Pendiente de financiera.",
    ),
    DECIMALES_ORDEN: DefinicionParametro(
        clave=DECIMALES_ORDEN, nombre="Decimales para cálculo de órdenes", tipo="entero", valor_por_defecto="0", minimo=0, decision="D-11",
        validador=validar_decimales_oferta, descripcion="Provisional: 0, 1 o 2 decimales. Los borradores nuevos conservan el cálculo adjudicado; aplicar parámetros actuales es una acción explícita. No recalcula documentos emitidos.",
    ),
    MODO_REDONDEO_ORDEN: DefinicionParametro(
        clave=MODO_REDONDEO_ORDEN, nombre="Modo de redondeo de órdenes", tipo="texto", valor_por_defecto="ROUND_HALF_UP", decision="D-11",
        validador=validar_redondeo_oferta, descripcion="Provisional, pendiente de financiera. ROUND_HALF_UP, ROUND_HALF_EVEN, ROUND_DOWN o ROUND_UP. Se conserva con los importes usados; no implica una tarifa fiscal oficial.",
    ),
    PREFIJO_ORDEN: DefinicionParametro(
        clave=PREFIJO_ORDEN, nombre="Prefijo del consecutivo de orden", tipo="texto", valor_por_defecto="OC", decision="D-12",
        validador=validar_prefijo_orden, descripcion="Provisional: OC. Se aplica al emitir; no cambia números asignados. Letras, números, guiones y guiones bajos, máximo 20 caracteres.",
    ),
    ANIO_ORDEN: DefinicionParametro(
        clave=ANIO_ORDEN, nombre="Incluir año en consecutivo de orden", tipo="booleano", valor_por_defecto="true", decision="D-12",
        descripcion="Provisional: Sí, usa el año de emisión en Bogotá. Si se activa reinicio anual debe incluir el año. No usa el año de elaboración ni renumera documentos existentes.",
    ),
    LONGITUD_ORDEN: DefinicionParametro(
        clave=LONGITUD_ORDEN, nombre="Dígitos mínimos del consecutivo de orden", tipo="entero", valor_por_defecto="4", minimo=1, decision="D-12",
        validador=validar_longitud_orden, descripcion="Provisional: mínimo 4 dígitos, con ceros a la izquierda. No limita la capacidad: 9999 continúa en 10000 sin truncar ni reutilizar. Admite longitudes 1 a 20.",
    ),
    REINICIO_ORDEN: DefinicionParametro(
        clave=REINICIO_ORDEN, nombre="Reinicio anual del consecutivo de orden", tipo="booleano", valor_por_defecto="false", decision="D-12",
        descripcion="Provisional: No, contador global. Sí mantiene contador por año de emisión y exige incluir el año. Los contadores nunca se borran ni retroceden; cambios de formato no reutilizan números existentes o anulados.",
    ),
    ETIQUETA_VALIDEZ_ORDEN: DefinicionParametro(
        clave=ETIQUETA_VALIDEZ_ORDEN, nombre="Etiqueta de fecha de validez/vencimiento de orden", tipo="texto", valor_por_defecto="Validez / vencimiento", decision="D-13",
        validador=validar_etiqueta_validez, descripcion="Etiqueta provisional para una fecha opcional cuyo significado sigue pendiente. Borradores usan la etiqueta actual; al emitir se conserva. No se interpreta automáticamente como plazo de entrega.",
    ),
    CAMPOS_CONTRATO: DefinicionParametro(
        clave=CAMPOS_CONTRATO, nombre="Campos obligatorios del contrato", tipo="texto", valor_por_defecto=CONTRATO_DEFECTO,
        validador=validar_campos_contrato,
        descripcion="Provisional: true exige el campo antes de aprobar una decisión que requiere contrato. PDF opcional inicialmente. supervisor admite usuario o texto. Puede guardar borradores incompletos. Los campos no se exigen si no requiere contrato.",
    ),
    CAMPOS_POLIZA: DefinicionParametro(
        clave=CAMPOS_POLIZA, nombre="Campos obligatorios de cada póliza", tipo="texto", valor_por_defecto=POLIZA_DEFECTO,
        validador=validar_campos_poliza,
        descripcion="Provisional: true exige el campo en cada póliza activa antes de aprobar. Inicialmente se exige también su PDF. No establece tipos de póliza ni porcentajes oficiales de cobertura. La obligación de tener alguna póliza se configura por separado.",
    ),
    EXIGIR_POLIZA: DefinicionParametro(
        clave=EXIGIR_POLIZA, nombre="Exigir al menos una póliza para el contrato", tipo="booleano", valor_por_defecto="false",
        descripcion="Provisional: No permite contratos sin pólizas. Sí exige al menos una póliza activa y completa antes de aprobar la decisión. No se aplica a compras que no requieren contrato. Pendiente de aprobación de la clínica.",
    ),
    MODALIDAD_ADJUDICACION: DefinicionParametro(
        clave=MODALIDAD_ADJUDICACION, nombre="Modalidad inicial de adjudicación", tipo="texto", valor_por_defecto="completa",
        validador=validar_modalidad_adjudicacion,
        descripcion="Oferta completa por elección del usuario. Alternativa lineas: cada línea a un oferente. Ambas modalidades están disponibles al proponer una decisión.",
    ),
    APROBACIONES_COTIZACION: DefinicionParametro(
        clave=APROBACIONES_COTIZACION, nombre="Aprobaciones requeridas para decidir cotizaciones", tipo="entero", valor_por_defecto="1", minimo=1,
        descripcion="Provisional: una aprobación administrativa. Se admiten varias de usuarios distintos; la regla queda fija en cada propuesta. Cambiarla afecta propuestas nuevas. Pendiente de aprobación de la clínica.",
    ),
    ROLES_DECISION_COTIZACION: DefinicionParametro(
        clave=ROLES_DECISION_COTIZACION, nombre="Roles que aprueban decisiones de cotización", tipo="texto", valor_por_defecto="administrador",
        validador=validar_roles_aprobadores,
        descripcion="Provisional: administrador. Puede habilitar también desarrollador. Cada propuesta conserva los roles requeridos; el usuario debe mantener un rol habilitado al aprobar.",
    ),
    CONTROL_VERIFICACIONES: DefinicionParametro(
        clave=CONTROL_VERIFICACIONES, nombre="Control de verificaciones al decidir cotizaciones", tipo="texto", valor_por_defecto="advertir",
        validador=validar_control_documental_elegibles,
        descripcion="Provisional: advertir exige justificación si una oferta seleccionada tiene verificaciones activas obligatorias en No, Pendiente o sin reconfirmar. bloquear impide aprobarla. Solo se revisan las ofertas seleccionadas. La regla se conserva por propuesta.",
    ),
    MIN_JUSTIFICACION_UNICO: DefinicionParametro(
        clave=MIN_JUSTIFICACION_UNICO, nombre="Mínimo de caracteres para justificar proveedor único", tipo="entero",
        valor_por_defecto="20", minimo=1,
        descripcion="Provisional, pendiente de aprobación de la clínica: mínimo 20 caracteres tras normalizar espacios. Nunca se admite justificación vacía. Se comprueba al confirmar el caso y antes de decidir la cotización.",
    ),
    EVIDENCIA_UNICO_OBLIGATORIA: DefinicionParametro(
        clave=EVIDENCIA_UNICO_OBLIGATORIA, nombre="Exigir PDF para proveedor único", tipo="booleano", valor_por_defecto="false",
        descripcion="Provisional, pendiente de aprobación de la clínica: No permite evidencia PDF opcional. Sí exige PDF al confirmar el caso y antes de decidir. Cambiar el parámetro no reescribe el historial; la decisión debe cumplir la regla vigente.",
    ),
    DECIMALES_OFERTA: DefinicionParametro(
        clave=DECIMALES_OFERTA, nombre="Decimales de importes de ofertas", tipo="entero", valor_por_defecto="0",
        minimo=0, decision="D-11", validador=validar_decimales_oferta,
        descripcion="Provisional: 0 redondea a pesos; también se admiten 1 o 2 decimales. Por línea se redondea cantidad × precio, luego el impuesto sobre ese subtotal; total = subtotal + impuesto. El encabezado suma los valores de líneas. Se conservan las reglas de cada guardado.",
    ),
    REDONDEO_OFERTA: DefinicionParametro(
        clave=REDONDEO_OFERTA, nombre="Modo de redondeo de ofertas", tipo="texto", valor_por_defecto="ROUND_HALF_UP",
        decision="D-11", validador=validar_redondeo_oferta,
        descripcion="Provisional: ROUND_HALF_UP por defecto. Alternativas ROUND_HALF_EVEN, ROUND_DOWN y ROUND_UP. Solo afecta nuevos guardados; las revisiones anteriores conservan reglas y resultados. No define IVA fijo ni aplica descuentos implícitos.",
    ),
    MAX_OFERENTES_COTIZACION: DefinicionParametro(
        clave=MAX_OFERENTES_COTIZACION, nombre="Máximo de proveedores invitados por cotización", tipo="entero",
        valor_por_defecto="3", minimo=0, decision="D-10",
        descripcion="Límite provisional pendiente de aprobación: 3 proveedores invitados por cotización. Use 0 para no imponer límite de negocio. La precarga no descarta elegidos silenciosamente; revise el parámetro o el origen si lo excede.",
    ),
    MAX_LINEAS_COTIZACION: DefinicionParametro(
        clave=MAX_LINEAS_COTIZACION, nombre="Máximo de líneas por cotización", tipo="entero",
        valor_por_defecto="10", minimo=0, decision="D-10",
        descripcion="Límite provisional pendiente de aprobación: 10 líneas de especificación por cotización. Use 0 para no imponer límite de negocio. Se exige al menos una línea y nunca se trunca la precarga automáticamente.",
    ),
    CONTROL_DOCUMENTAL_ELEGIBLES: DefinicionParametro(
        clave=CONTROL_DOCUMENTAL_ELEGIBLES, nombre="Control documental al cerrar elegibles (pendiente)", tipo="texto",
        valor_por_defecto="advertir", validador=validar_control_documental_elegibles,
        descripcion="Regla provisional: advertir permite continuar con justificación si un proveedor elegido tiene alertas. bloquear impide cerrar si un elegido no tiene FR14 vigente (incluida antigüedad o fecha futura) o tiene documentos obligatorios vencidos. Faltantes y vencidos opcionales exigen justificación si se permite continuar; próximos a vencer son informativos. Solo aplica a cantidad autorizada > 0. Las fotos de listas cerradas se conservan.",
    ),
    MESES_EVALUACION_ELEGIBLES: DefinicionParametro(
        clave=MESES_EVALUACION_ELEGIBLES, nombre="Antigüedad máxima de FR14 para elegibles (meses, pendiente)", tipo="entero",
        valor_por_defecto="12", minimo=1,
        descripcion="Provisional, pendiente de aprobación de la clínica: 12 meses calendario desde la fecha de evaluación. El aniversario es válido; se considera antigua a partir del día siguiente. Se ajusta al último día del mes cuando corresponde. La referencia es la fecha de revisión/cierre en Bogotá, no la fecha de creación de la lista.",
    ),
    REGLAS_ELEGIBLES: DefinicionParametro(
        clave=REGLAS_ELEGIBLES, nombre="Reglas de cálculo de elegibles FR-GDS-20 (D-07)", tipo="texto",
        valor_por_defecto=REGLAS_ELEGIBLES_DEFECTO, decision="D-07", validador=validar_reglas_elegibles,
        descripcion='JSON: metodo directo = cumplimiento × (peso % / 100), máximo igual al máximo de la escala; escalado = cumplimiento / máximo × peso %, máximo 100. Escala inicial 5/3/1. Provisional: pendiente=true; cambiar a false solo tras aprobación de la clínica. Cada lista conserva sus reglas al asignarle versión; cambios solo afectan nuevas asignaciones.',
    ),
    BLOQUEAR_SI_VENCIDO: DefinicionParametro(
        clave=BLOQUEAR_SI_VENCIDO, nombre="Bloquear Sí con evidencia documental vencida",
        tipo="booleano", valor_por_defecto="false", decision="D-05",
        descripcion="Por defecto No: se permite responder Sí con advertencia si la evidencia asociada está vencida a la fecha de la evaluación. Sí bloquea esa respuesta. La evidencia no expedida a esa fecha tampoco es vigente. No define documentos obligatorios oficiales ni bloquea faltantes automáticamente.",
    ),
    REGLAS_FR14: DefinicionParametro(
        clave=REGLAS_FR14, nombre="Reglas de cálculo FR-GDS-14 (D-06)", tipo="texto",
        valor_por_defecto=REGLAS_FR14_DEFECTO, decision="D-06", validador=validar_reglas_fr14,
        descripcion='Regla provisional: Sí = peso × si, No = peso × no; N/A se excluye si excluir_na es true. Calificación 5 desde umbral5, 3 desde umbral3 y 1 por debajo. Valores iniciales 60/80 pendientes de aprobación, no oficiales. Edite el JSON completo; pendiente=false solo tras aprobación de la clínica. Las evaluaciones finalizadas conservan sus reglas.',
    ),
    CONSERVAR_PDF_DESCARTADO: DefinicionParametro(
        clave=CONSERVAR_PDF_DESCARTADO, nombre="Conservar PDF de envíos descartados",
        tipo="booleano", valor_por_defecto="true",
        descripcion="Sí conserva el PDF descartado para consulta del historial. Si se elige No, el archivo se elimina después del commit si no tiene otras referencias. El historial del envío siempre se conserva. Por defecto: Sí, pendiente de la política de retención de la clínica. Cambiarlo no elimina archivos de descartes anteriores.",
    ),
    ACTIVAR_REGISTRO_PORTAL: DefinicionParametro(
        clave=ACTIVAR_REGISTRO_PORTAL, nombre="Activar cuentas al registrarse en el portal",
        tipo="booleano", valor_por_defecto="true", decision="D-03",
        descripcion="Sí permite ingresar inmediatamente con la clave elegida. No deja la cuenta inactiva hasta que administración la active. No aprueba la ficha del proveedor. Pendiente de confirmación por la clínica.",
    ),
    PERMITIR_DEVOLUCION: DefinicionParametro(
        clave=PERMITIR_DEVOLUCION,
        nombre="Permitir devolver proyecciones al área",
        tipo="booleano",
        valor_por_defecto="true",
        descripcion=(
            "Si está en Sí, administración puede devolver una proyección enviada al área para que la "
            "corrija; vuelve a borrador. Si está en No, administración solo puede corregirla directamente. "
            "Valor por defecto: Sí, mientras la clínica confirma la decisión D-01."
        ),
        decision="D-01",
    ),
    APROBACIONES_REQUERIDAS: DefinicionParametro(
        clave=APROBACIONES_REQUERIDAS,
        nombre="Aprobaciones requeridas por proyección",
        tipo="entero",
        valor_por_defecto="1",
        descripcion=(
            "Número de administradores distintos que deben aprobar un envío para que la proyección quede "
            "aprobada. Valor por defecto: 1, mientras la clínica confirma la decisión D-01 (una o varias "
            "aprobaciones)."
        ),
        decision="D-01",
        minimo=1,
    ),
    ROLES_APROBADORES_PROVEEDOR: DefinicionParametro(
        clave=ROLES_APROBADORES_PROVEEDOR,
        nombre="Roles que pueden aprobar proveedores",
        tipo="texto",
        valor_por_defecto="administrador,desarrollador",
        descripcion=(
            "Roles, separados por coma, que pueden pasar un proveedor al estado «Aprobado». Valores posibles: "
            "administrador, desarrollador. Valor por defecto: administrador,desarrollador, mientras la clínica "
            "confirma la decisión D-03 (quién aprueba proveedores)."
        ),
        decision="D-03",
        validador=validar_roles_aprobadores,
    ),
    DIAS_ALERTA_VENCIMIENTO: DefinicionParametro(
        clave=DIAS_ALERTA_VENCIMIENTO,
        nombre="Días de aviso antes del vencimiento de documentos",
        tipo="entero",
        valor_por_defecto="30",
        descripcion=(
            "Un documento de proveedor aparece en la alerta «por vencer» cuando le quedan estos días o menos. "
            "Los documentos ya vencidos siempre aparecen. Valor por defecto: 30."
        ),
        minimo=1,
    ),
}
