from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from decimal import Decimal
from threading import Barrier
from uuid import uuid4

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, connections, transaction
from django.db.models.deletion import ProtectedError
from django.test import RequestFactory, TestCase, TransactionTestCase, skipUnlessDBFeature
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase, APIClient

from apps.clientes.models import Cliente
from apps.vendas.models import ItemVenda, Venda
from apps.vendas.services import cancelar_venda
from apps.vendas.tests import VendaFixtureMixin

from .models import Pagamento, Parcela
from .services import estornar_pagamento, registrar_pagamento, resumo_financeiro


class PagamentoServiceTests(VendaFixtureMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.sale = self.venda()
        self.parcela = self.sale.parcelas.first()

    def test_pagamento_completo(self):
        pagamento = self.pagar(self.parcela, "500.00")
        self.assertEqual(self.parcela.valor_pago, Decimal("500.00"))
        self.assertEqual(self.parcela.saldo_restante, Decimal("0.00"))
        self.assertEqual(self.parcela.status, "paga")
        self.assertEqual(self.parcela.data_quitacao, pagamento.data_pagamento)

    def test_pagamentos_parciais_acumulados(self):
        self.pagar(self.parcela, "200.00")
        self.assertEqual(self.parcela.status, "parcial")
        self.assertEqual(self.parcela.saldo_restante, Decimal("300.00"))
        self.assertIsNone(self.parcela.data_quitacao)
        self.pagar(self.parcela, "300.00")
        self.assertEqual(self.parcela.valor_pago, Decimal("500.00"))
        self.assertEqual(self.parcela.status, "paga")
        self.assertEqual(self.parcela.pagamentos.count(), 2)

    def test_saldo_insuficiente_e_valores_invalidos(self):
        for valor in ("500.01", "-1.00", "0.00", "0.001", 1.5):
            with self.subTest(valor=valor), self.assertRaises(ValidationError):
                self.pagar(self.parcela, valor)
        self.assertEqual(self.parcela.pagamentos.count(), 0)
        self.pagar(self.parcela, "200.00")
        with self.assertRaises(ValidationError):
            self.pagar(self.parcela, "300.01")

    def test_idempotencia_e_conflito(self):
        chave = uuid4()
        primeiro = self.pagar(self.parcela, "500.00", chave_idempotencia=chave)
        self.assertEqual(self.pagar(self.parcela, "500.00", chave_idempotencia=chave).pk, primeiro.pk)
        self.assertEqual(self.parcela.pagamentos.count(), 1)
        with self.assertRaises(ValidationError):
            self.pagar(self.parcela, "100.00", chave_idempotencia=chave)

    def test_idempotencia_nao_pode_ser_reutilizada_por_outro_usuario(self):
        chave = uuid4()
        self.pagar(self.parcela, chave_idempotencia=chave)
        outro = get_user_model().objects.create_user(username="outro")
        with self.assertRaises(ValidationError):
            self.pagar(self.parcela, chave_idempotencia=chave, usuario=outro)

    def test_estorno_rastreavel_saldo_historico_e_idempotencia(self):
        pagamento = self.pagar(self.parcela, "500.00")
        estornado = estornar_pagamento(pagamento_id=pagamento.pk, usuario=self.user, motivo="Lançamento incorreto")
        self.assertEqual(estornado.status, "estornado")
        self.assertEqual(estornado.estornado_por, self.user)
        self.assertIsNotNone(estornado.estornado_em)
        self.assertEqual(self.parcela.valor_pago, Decimal("0.00"))
        self.assertEqual(self.parcela.saldo_restante, Decimal("500.00"))
        self.assertIsNone(self.parcela.data_quitacao)
        self.assertEqual(self.parcela.pagamentos.count(), 1)
        repetido = estornar_pagamento(pagamento_id=pagamento.pk, usuario=self.user, motivo="Lançamento incorreto")
        self.assertEqual(repetido.estornado_em, estornado.estornado_em)
        with self.assertRaises(ValidationError):
            estornar_pagamento(pagamento_id=pagamento.pk, usuario=self.user, motivo="Outro motivo")

    def test_motivos_obrigatorios(self):
        pagamento = self.pagar(self.parcela)
        with self.assertRaises(ValidationError):
            estornar_pagamento(pagamento_id=pagamento.pk, usuario=self.user, motivo="  ")
        with self.assertRaises(ValidationError):
            cancelar_venda(venda_id=self.sale.pk, usuario=self.user, motivo="  ")

    def test_repeticao_apos_estorno_nao_recria_recebimento(self):
        chave = uuid4()
        pagamento = self.pagar(self.parcela, chave_idempotencia=chave)
        estornar_pagamento(pagamento_id=pagamento.pk, usuario=self.user, motivo="Erro")
        repetido = self.pagar(self.parcela, chave_idempotencia=chave)
        self.assertEqual(repetido.pk, pagamento.pk)
        self.assertEqual(repetido.status, "estornado")
        self.assertEqual(self.parcela.valor_pago, Decimal("0.00"))

    def test_nao_paga_venda_cancelada(self):
        estornar_pagamento(pagamento_id=self.sale.pagamentos.get().pk, usuario=self.user, motivo="Erro")
        cancelar_venda(venda_id=self.sale.pk, usuario=self.user, motivo="Erro")
        with self.assertRaises(ValidationError):
            self.pagar(self.parcela)

    def test_datas_e_situacao_vencida_prevalece_sobre_parcial(self):
        vencida = self.venda(primeiro_vencimento=timezone.localdate() - timedelta(days=1)).parcelas.first()
        self.assertEqual(vencida.status, "vencida")
        self.pagar(vencida, "200.00")
        self.assertEqual(vencida.status, "vencida")
        self.pagar(vencida, "300.00")
        self.assertEqual(vencida.status, "paga")
        hoje = self.venda(primeiro_vencimento=timezone.localdate()).parcelas.first()
        self.assertEqual(hoje.status, "pendente")

    def test_data_pagamento_futura_bloqueada(self):
        with self.assertRaises(ValidationError):
            self.pagar(self.parcela, data_pagamento=timezone.now() + timedelta(days=1))

    def test_resumo_sem_dupla_contagem_e_apos_estorno(self):
        pagamento = self.pagar(self.parcela, "200.00")
        resumo = resumo_financeiro(self.cliente.pk)
        self.assertEqual(resumo["total_compras"], Decimal("2400.00"))
        self.assertEqual(resumo["total_entradas_recebidas"], Decimal("400.00"))
        self.assertEqual(resumo["total_pago_parcelas"], Decimal("200.00"))
        self.assertEqual(resumo["total_efetivamente_pago"], Decimal("600.00"))
        self.assertEqual(resumo["saldo_devedor"], Decimal("1800.00"))
        self.assertEqual(resumo["parcelas_pendentes"], 4)
        estornar_pagamento(pagamento_id=pagamento.pk, usuario=self.user, motivo="Erro")
        self.assertEqual(resumo_financeiro(self.cliente.pk)["saldo_devedor"], Decimal("2000.00"))

    def test_entrada_estornada_permanece_no_saldo_ate_cancelamento(self):
        entrada = self.sale.pagamentos.get()
        estornar_pagamento(pagamento_id=entrada.pk, usuario=self.user, motivo="Correção")
        resumo = resumo_financeiro(self.cliente.pk)
        self.assertEqual(resumo["saldo_devedor"], Decimal("2400.00"))
        self.assertEqual(resumo["saldo_entrada_estornada"], Decimal("400.00"))
        cancelar_venda(venda_id=self.sale.pk, usuario=self.user, motivo="Erro")
        resumo = resumo_financeiro(self.cliente.pk)
        self.assertEqual(resumo["saldo_devedor"], Decimal("0.00"))
        self.assertEqual(resumo["total_compras"], Decimal("0.00"))
        self.assertEqual(resumo["parcelas_pendentes"], 0)

    def test_resumo_a_vista_e_sem_vendas(self):
        outro = Cliente.objects.create(nome="Bia", telefone="85999991234")
        self.assertEqual(resumo_financeiro(outro.pk)["saldo_devedor"], Decimal("0.00"))
        self.venda(cliente_id=outro.pk, valor_entrada="2400.00", quantidade_parcelas=0, primeiro_vencimento=None)
        resumo = resumo_financeiro(outro.pk)
        self.assertEqual(resumo["saldo_devedor"], Decimal("0.00"))
        self.assertEqual(resumo["total_efetivamente_pago"], Decimal("2400.00"))
        self.assertEqual(resumo["parcelas_quitadas"], 0)

    def test_historico_bloqueia_edicao_e_exclusao(self):
        pagamento = self.pagar(self.parcela)
        for obj in (self.sale, self.sale.itens.first(), self.parcela, pagamento):
            with self.subTest(model=type(obj).__name__):
                with self.assertRaises(ValidationError):
                    obj.save()
                with self.assertRaises(ValidationError):
                    obj.delete()
                with self.assertRaises(ValidationError):
                    type(obj).objects.filter(pk=obj.pk).delete()
        with self.assertRaises(ValidationError):
            Pagamento.objects.filter(pk=pagamento.pk).update(valor=Decimal("1.00"))
        with self.assertRaises(ProtectedError):
            self.user.delete()

    def test_restricoes_financeiras_no_banco(self):
        pagamento = self.pagar(self.parcela)
        # Deliberately bypass the ORM only inside the isolated test database.
        cases = (
            ("vendas_venda", self.sale.pk, "valor_entrada", Decimal("-1.00")),
            ("vendas_venda", self.sale.pk, "valor_financiado", Decimal("1.00")),
            ("vendas_itemvenda", self.sale.itens.get().pk, "valor_total", Decimal("1.00")),
            ("financeiro_parcela", self.parcela.pk, "valor_original", Decimal("0.00")),
            ("financeiro_pagamento", pagamento.pk, "valor", Decimal("0.00")),
            ("financeiro_pagamento", pagamento.pk, "status", "estornado"),
        )
        for table, pk, field, value in cases:
            with self.subTest(table=table, field=field):
                with self.assertRaises(IntegrityError), transaction.atomic():
                    with connection.cursor() as cursor:
                        cursor.execute(f'UPDATE "{table}" SET "{field}" = %s WHERE id = %s', [value, pk])

    def test_gravacoes_em_lote_bloqueadas(self):
        for model in (Venda, ItemVenda, Parcela, Pagamento):
            with self.subTest(model=model.__name__):
                with self.assertRaises(ValidationError):
                    model.objects.bulk_create([])
                with self.assertRaises(ValidationError):
                    model.objects.bulk_update([], ["id"])

    def test_operacao_exige_usuario_ativo(self):
        self.user.is_active = False
        with self.assertRaises(ValidationError):
            self.pagar(self.parcela)


class FinanceiroAPITests(VendaFixtureMixin, APITestCase):
    def setUp(self):
        super().setUp()
        self.client.force_authenticate(self.user)
        self.sale = self.venda()
        self.parcela = self.sale.parcelas.first()
        self.url = reverse("pagamento-list")

    def payload(self, **changes):
        return {"parcela": self.parcela.pk, "valor": "200.00", "forma_pagamento": "pix", "chave_idempotencia": str(uuid4()), **changes}

    def test_pagamento_consulta_estorno(self):
        response = self.client.post(self.url, self.payload(), format="json")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["responsavel"], self.user.pk)
        pk = response.data["id"]
        self.assertEqual(self.client.get(reverse("pagamento-detail", args=[pk])).status_code, 200)
        response = self.client.post(reverse("pagamento-estornar", args=[pk]), {"motivo": "Erro"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], "estornado")

    def test_idempotencia_e_chave_obrigatoria(self):
        data = self.payload()
        first = self.client.post(self.url, data, format="json")
        second = self.client.post(self.url, data, format="json")
        self.assertEqual(first.status_code, 201)
        self.assertEqual(first.data["id"], second.data["id"])
        conflict = self.client.post(self.url, {**data, "valor": "300.00"}, format="json")
        self.assertEqual(conflict.status_code, 400)
        self.assertIn("chave_idempotencia", conflict.data)
        data.pop("chave_idempotencia")
        self.assertEqual(self.client.post(self.url, data, format="json").status_code, 400)

    def test_validacao_campos_e_erro_de_dominio(self):
        for change, field in (({"valor": "501.00"}, "valor"), ({"valor": "0"}, "valor"),
                              ({"parcela": 999999}, "parcela"), ({"status": "valido"}, "status"),
                              ({"responsavel": self.user.pk}, "responsavel")):
            response = self.client.post(self.url, self.payload(**change), format="json")
            self.assertEqual(response.status_code, 400)
            self.assertIn(field, response.data)

    def test_resumo_financeiro_cliente(self):
        self.pagar(self.parcela)
        response = self.client.get(reverse("cliente-resumo-financeiro", args=[self.cliente.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["saldo_devedor"], "1900.00")
        self.assertEqual(response.data["total_efetivamente_pago"], "500.00")
        self.assertEqual(self.client.get(reverse("cliente-resumo-financeiro", args=[999999])).status_code, 404)

    def test_filtros_parcelas_e_contagens_resumo(self):
        outra = self.venda(primeiro_vencimento=timezone.localdate() - timedelta(days=1)).parcelas.first()
        self.pagar(outra, "200.00")
        self.pagar(self.parcela, "500.00")
        url = reverse("parcela-list")
        vencidas = self.client.get(url, {"status": "vencida"})
        self.assertEqual(vencidas.status_code, 200)
        self.assertEqual(vencidas.data["count"], 1)
        self.assertEqual(vencidas.data["results"][0]["id"], outra.pk)
        pagas = self.client.get(url, {"status": "paga", "venda": self.sale.pk})
        self.assertEqual(pagas.data["count"], 1)
        self.assertIsNotNone(pagas.data["results"][0]["data_quitacao"])
        self.assertEqual(self.client.get(url, {"status": "pendente", "venda": self.sale.pk}).data["count"], 3)
        self.assertEqual(self.client.get(url, {"status": "errado"}).status_code, 400)
        resumo = resumo_financeiro(self.cliente.pk)
        self.assertEqual(resumo["parcelas_vencidas"], 1)
        self.assertEqual(resumo["parcelas_quitadas"], 1)

    def test_filtros_pagamentos_periodo_status_e_vencimento(self):
        self.pagar(self.parcela)
        response = self.client.get(self.url, {"cliente": self.cliente.pk, "tipo": "parcela", "status": "valido"})
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(self.client.get(self.url, {"data_inicio": "2000-01-01", "data_fim": "2000-01-02"}).data["count"], 0)
        response = self.client.get(reverse("parcela-list"), {"vencimento_inicio": "2030-02-01", "vencimento_fim": "2030-02-28"})
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(self.client.get(self.url, {"data_inicio": "2030-02-01", "data_fim": "2030-01-01"}).status_code, 400)

    def test_sem_edicao_ou_exclusao_e_criacao_de_parcelas(self):
        pagamento = self.pagar(self.parcela)
        for url in (reverse("pagamento-detail", args=[pagamento.pk]), reverse("parcela-detail", args=[self.parcela.pk])):
            for method in ("delete", "put", "patch"):
                with self.subTest(url=url, method=method):
                    self.assertEqual(getattr(self.client, method)(url, {}, format="json").status_code, 405)
        self.assertEqual(self.client.post(reverse("parcela-list"), {}).status_code, 405)

    def test_endpoints_bloqueados_sem_sessao(self):
        pagamento = self.pagar(self.parcela)
        self.client.force_authenticate(user=None)
        requests = [
            ("get", reverse("venda-list")), ("post", reverse("venda-list")),
            ("get", reverse("venda-detail", args=[self.sale.pk])),
            ("post", reverse("venda-cancelar", args=[self.sale.pk])),
            ("get", reverse("venda-parcelas", args=[self.sale.pk])),
            ("get", reverse("parcela-list")), ("get", reverse("parcela-detail", args=[self.parcela.pk])),
            ("get", self.url), ("post", self.url),
            ("get", reverse("pagamento-detail", args=[pagamento.pk])),
            ("post", reverse("pagamento-estornar", args=[pagamento.pk])),
            ("get", reverse("cliente-resumo-financeiro", args=[self.cliente.pk])),
        ]
        for method, url in requests:
            with self.subTest(method=method, url=url):
                self.assertEqual(getattr(self.client, method)(url).status_code, 403)

    def test_sessao_exige_csrf_para_escrita(self):
        client = APIClient(enforce_csrf_checks=True)
        client.force_login(self.user)
        self.assertEqual(client.post(self.url, self.payload(), format="json").status_code, 403)
        self.assertEqual(client.get(self.url).status_code, 200)

    def test_paginacao_parcelas(self):
        self.venda(quantidade_parcelas=26)
        response = self.client.get(reverse("parcela-list"))
        self.assertEqual(response.data["count"], 30)
        self.assertEqual(len(response.data["results"]), 25)
        self.assertIsNotNone(response.data["next"])


class FinanceiroAdminTests(VendaFixtureMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.admin_user = get_user_model().objects.create_superuser(username="finance-admin", password="teste-seguro", email="admin@example.com")
        self.client.force_login(self.admin_user)
        self.sale = self.venda()
        self.parcela = self.sale.parcelas.first()
        self.pagamento = self.pagar(self.parcela)

    def test_registros_e_paginas_de_consulta(self):
        for obj in (self.sale, self.parcela, self.pagamento):
            model = type(obj)
            self.assertIn(model, admin.site._registry)
            name = f"admin:{model._meta.app_label}_{model._meta.model_name}"
            response = self.client.get(reverse(name + "_changelist"))
            self.assertEqual(response.status_code, 200)
            response = self.client.get(reverse(name + "_change", args=[obj.pk]))
            self.assertEqual(response.status_code, 200)

    def test_sem_permissoes_de_escrita_nem_acoes_em_massa(self):
        request = RequestFactory().get("/admin/")
        request.user = self.admin_user
        for obj in (self.sale, self.parcela, self.pagamento):
            model = type(obj)
            model_admin = admin.site._registry[model]
            self.assertFalse(model_admin.has_add_permission(request))
            self.assertFalse(model_admin.has_change_permission(request, obj))
            self.assertFalse(model_admin.has_delete_permission(request, obj))
            self.assertEqual(model_admin.get_actions(request), {})
            name = f"admin:{model._meta.app_label}_{model._meta.model_name}"
            self.assertEqual(self.client.post(reverse(name + "_change", args=[obj.pk]), {"valor": "1.00"}).status_code, 403)
            self.assertEqual(self.client.post(reverse(name + "_delete", args=[obj.pk]), {"post": "yes"}).status_code, 403)
            self.assertEqual(self.client.get(reverse(name + "_add")).status_code, 403)
        self.pagamento.refresh_from_db()
        self.assertEqual(self.pagamento.valor, Decimal("100.00"))

    def test_usuario_comum_sem_acesso_ao_admin(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse("admin:vendas_venda_changelist")).status_code, 302)


@skipUnlessDBFeature("has_select_for_update")
class PagamentoConcurrencyTests(VendaFixtureMixin, TransactionTestCase):
    def test_pagamentos_simultaneos_nao_ultrapassam_saldo(self):
        sale = self.venda()
        parcela = sale.parcelas.first()
        barreira = Barrier(2)

        def pagar(chave):
            try:
                usuario = get_user_model().objects.get(pk=self.user.pk)
                barreira.wait(timeout=10)
                try:
                    registrar_pagamento(parcela_id=parcela.pk, valor="300.00", forma_pagamento="pix", usuario=usuario, chave_idempotencia=chave)
                    return "ok"
                except ValidationError:
                    return "saldo_insuficiente"
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(pagar, uuid4()) for _ in range(2)]
            resultados = [future.result(timeout=30) for future in futures]
        self.assertCountEqual(resultados, ["ok", "saldo_insuficiente"])
        self.assertEqual(parcela.valor_pago, Decimal("300.00"))
        self.assertEqual(parcela.pagamentos.count(), 1)

    def test_requisicoes_simultaneas_mesma_chave(self):
        sale = self.venda()
        parcela = sale.parcelas.first()
        chave = uuid4()
        barreira = Barrier(2)

        def pagar():
            try:
                usuario = get_user_model().objects.get(pk=self.user.pk)
                barreira.wait(timeout=10)
                return registrar_pagamento(parcela_id=parcela.pk, valor="500.00", forma_pagamento="pix", usuario=usuario, chave_idempotencia=chave).pk
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(pagar) for _ in range(2)]
            ids = [future.result(timeout=30) for future in futures]
        self.assertEqual(ids[0], ids[1])
        self.assertEqual(parcela.pagamentos.count(), 1)
        self.assertEqual(parcela.saldo_restante, Decimal("0.00"))
