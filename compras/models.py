"""Punto de importación estable de los modelos de compras.

Las definiciones se agrupan en compras/modelos; se conservan nombres, tablas y
etiquetas de Django para servicios, migraciones y módulos existentes.
"""
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models.functions import Lower
from django.utils import timezone

from config.utilidades import normalizar_espacios

from compras.modelos.comunes import (
    OfertaProtegidaQuerySet,
)
from compras.modelos.necesidades import (
    TipoOrigen,
    Necesidad,
    OrigenNecesidad,
)
from compras.modelos.elegibles import (
    ListaElegibles,
    ParticipanteElegible,
    CatalogoCriteriosQuerySet,
    VersionCriterios,
    CriterioElegible,
    CalificacionElegible,
    DesempateElegibles,
    DecisionElegibles,
    HistorialCierreQuerySet,
    CierreListaElegibles,
)
from compras.modelos.cotizaciones import (
    TipoCotizacion,
    SecuenciaCotizacion,
    CotizacionQuerySet,
    Cotizacion,
    LineaCotizacion,
    InvitadoCotizacion,
)
from compras.modelos.ofertas import (
    TarifaImpuesto,
    TipoRetencion,
    Oferta,
    OfertaLinea,
    PdfOferta,
    RevisionOferta,
)
from compras.modelos.verificaciones import (
    TipoVerificacion,
    EstadoVerificacion,
    VerificacionOferta,
    PdfVerificacionOferta,
    RevisionVerificacionOferta,
)
from compras.modelos.proveedor_unico import (
    CausalProveedorUnico,
    PdfProveedorUnico,
    RevisionProveedorUnico,
)
from compras.modelos.decisiones import (
    DecisionCotizacion,
    AdjudicacionCotizacion,
    AprobacionCotizacion,
)
from compras.modelos.contratos import (
    _contrato_editable,
    TipoPoliza,
    Contrato,
    Poliza,
    PdfContractual,
    RevisionContrato,
)
from compras.modelos.ordenes import (
    OrdenCompra,
    OrdenLinea,
    RevisionOrdenCompra,
    ContadorOrdenCompra,
)

from compras.operacion_models import AprobacionOrden, EvidenciaEnvioOrden, ReglaAprobacionOrden, SolicitudAprobacionOrden
from compras.operacion_models import Recepcion, RecepcionLinea
