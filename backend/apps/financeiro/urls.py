from rest_framework.routers import DefaultRouter

from .views import PagamentoViewSet, ParcelaViewSet

router = DefaultRouter()
router.register("parcelas", ParcelaViewSet, basename="parcela")
router.register("pagamentos", PagamentoViewSet, basename="pagamento")
urlpatterns = router.urls
