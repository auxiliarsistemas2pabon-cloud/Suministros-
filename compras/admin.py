from django.contrib import admin
from compras.models import CalificacionElegible, CriterioElegible, ListaElegibles, Necesidad, OrigenNecesidad, ParticipanteElegible, TipoOrigen, VersionCriterios
from proyecciones.admin import SoloLecturaAdmin
from compras.models import DecisionElegibles, DesempateElegibles
from compras.models import CierreListaElegibles
from compras.models import Cotizacion, InvitadoCotizacion, LineaCotizacion, SecuenciaCotizacion, TipoCotizacion
from compras.models import Oferta, OfertaLinea, PdfOferta, RevisionOferta, TarifaImpuesto
from compras.models import EstadoVerificacion, PdfVerificacionOferta, RevisionVerificacionOferta, TipoVerificacion, VerificacionOferta
from compras.models import CausalProveedorUnico, PdfProveedorUnico, RevisionProveedorUnico
from compras.models import AdjudicacionCotizacion, AprobacionCotizacion, DecisionCotizacion
from compras.models import Contrato, PdfContractual, Poliza, RevisionContrato, TipoPoliza
from compras.models import OrdenCompra, OrdenLinea, RevisionOrdenCompra
from compras.models import ContadorOrdenCompra

for modelo in (ListaElegibles, Necesidad, OrigenNecesidad, ParticipanteElegible, TipoOrigen, VersionCriterios, CriterioElegible, CalificacionElegible, DecisionElegibles, DesempateElegibles, CierreListaElegibles):
    admin.site.register(modelo, SoloLecturaAdmin)

for modelo in (Cotizacion, InvitadoCotizacion, LineaCotizacion, SecuenciaCotizacion, TipoCotizacion):
    admin.site.register(modelo, SoloLecturaAdmin)

for modelo in (Oferta, OfertaLinea, PdfOferta, RevisionOferta, TarifaImpuesto):
    admin.site.register(modelo, SoloLecturaAdmin)

for modelo in (EstadoVerificacion, PdfVerificacionOferta, RevisionVerificacionOferta, TipoVerificacion, VerificacionOferta):
    admin.site.register(modelo, SoloLecturaAdmin)

for modelo in (CausalProveedorUnico, PdfProveedorUnico, RevisionProveedorUnico):
    admin.site.register(modelo, SoloLecturaAdmin)

for modelo in (DecisionCotizacion, AdjudicacionCotizacion, AprobacionCotizacion):
    admin.site.register(modelo, SoloLecturaAdmin)

for modelo in (Contrato, Poliza, TipoPoliza, PdfContractual, RevisionContrato):
    admin.site.register(modelo, SoloLecturaAdmin)

for modelo in (OrdenCompra, OrdenLinea, RevisionOrdenCompra):
    admin.site.register(modelo, SoloLecturaAdmin)

admin.site.register(ContadorOrdenCompra, SoloLecturaAdmin)
