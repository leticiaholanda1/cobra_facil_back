"""Fluxo real pela API; executar exclusivamente em PostgreSQL de testes."""
from datetime import date
from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TransactionTestCase
from django.urls import reverse
from rest_framework.test import APIClient

from apps.clientes.models import Cliente
from apps.vendas.models import ItemVenda, Venda

from .models import Pagamento, Parcela


class FluxoCrediarioIntegracaoTests(TransactionTestCase):
    @classmethod
    def setUpClass(cls):
        # Conferir antes de qualquer fixture ou limpeza transacional do Django.
        nome = str(connection.settings_dict["NAME"])
        if connection.vendor != "postgresql" or not nome.startswith("test_"):
            raise RuntimeError("A integração exige um PostgreSQL isolado com nome test_*.")
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_database()")
            if cursor.fetchone()[0] != nome:
                raise RuntimeError("O banco conectado difere do banco de testes configurado.")
        super().setUpClass()

    def setUp(self):
        super().setUp()
        # Apenas o calendário é controlado; banco, sessão e serviços são reais.
        calendario = patch("django.utils.timezone.localdate", return_value=date(2026, 11, 7))
        calendario.start()
        self.addCleanup(calendario.stop)
        self.usuario = get_user_model().objects.create_user(username="operador-integracao")
        self.client = APIClient(enforce_csrf_checks=True)
        self.client.force_login(self.usuario)
        login = self.client.get(reverse("admin:login"))
        self.assertEqual(login.status_code, 200)
        self.client.credentials(HTTP_X_CSRFTOKEN=self.client.cookies["csrftoken"].value)
        resposta = self.client.post(reverse("cliente-list"), {
            "nome": "Cliente Teste Integração", "telefone": "(85) 99999-0000", "ativo": True,
        }, format="json")
        self.assertEqual(resposta.status_code, 201, resposta.data)
        self.cliente = Cliente.objects.get(pk=resposta.data["id"])
        self.assertEqual(self.cliente.nome, "Cliente Teste Integração")
        self.assertEqual(self.cliente.telefone, "(85) 99999-0000")
        self.assertTrue(self.cliente.ativo)
        self.assertIsNone(self.cliente.cpf)
        self.dados_venda = {
            "cliente": self.cliente.pk,
            "itens": [{"descricao": "Geladeira", "quantidade": 1, "valor_unitario": "2400.00"}],
            "valor_total": "2400.00", "valor_entrada": "400.00", "forma_entrada": "pix",
            "quantidade_parcelas": 4, "primeiro_vencimento": "2026-12-10",
            "chave_idempotencia": str(uuid4()),
        }

    def consultar(self, nome, *args, parametros=None):
        resposta = self.client.get(reverse(nome, args=args), parametros or {})
        self.assertEqual(resposta.status_code, 200, resposta.data)
        return resposta.data

    def criar_venda(self):
        resposta = self.client.post(reverse("venda-list"), self.dados_venda, format="json")
        self.assertEqual(resposta.status_code, 201, resposta.data)
        self.venda = Venda.objects.get(pk=resposta.data["id"])
        self.assertEqual(self.venda.cliente_id, self.cliente.pk)
        self.assertEqual(self.venda.responsavel_id, self.usuario.pk)
        self.assertEqual(self.venda.data_venda, date(2026, 11, 7))
        self.assertEqual(self.venda.status, "ativa")
        self.assertEqual(self.venda.valor_total, Decimal("2400.00"))
        self.assertEqual(self.venda.valor_entrada, Decimal("400.00"))
        self.assertEqual(self.venda.valor_financiado, Decimal("2000.00"))
        item = self.venda.itens.get()
        self.assertEqual((item.descricao, item.quantidade), ("Geladeira", 1))
        self.assertEqual(item.valor_unitario, Decimal("2400.00"))
        self.assertEqual(item.valor_total, Decimal("2400.00"))
        parcelas = list(self.venda.parcelas.order_by("numero"))
        self.assertEqual(len(parcelas), 4)
        self.assertEqual([p.numero for p in parcelas], [1, 2, 3, 4])
        self.assertEqual(len({p.pk for p in parcelas}), 4)
        self.assertEqual([p.vencimento for p in parcelas], [
            date(2026, 12, 10), date(2027, 1, 10), date(2027, 2, 10), date(2027, 3, 10),
        ])
        for parcela in parcelas:
            self.assertIsInstance(parcela.valor_original, Decimal)
            self.assertEqual(parcela.valor_original, Decimal("500.00"))
            self.assertEqual(parcela.valor_pago, Decimal("0.00"))
            self.assertEqual(parcela.saldo_restante, Decimal("500.00"))
            self.assertEqual(parcela.status, "pendente")
        self.assertEqual(sum((p.valor_original for p in parcelas), Decimal("0.00")),
                         self.venda.valor_financiado)
        self.primeira = parcelas[0]
        self.entrada = self.venda.pagamentos.get()
        self.assertEqual(self.entrada.tipo, "entrada")
        self.assertEqual(self.entrada.valor, Decimal("400.00"))
        self.assertEqual(self.entrada.forma_pagamento, "pix")
        self.assertEqual(self.entrada.status, "valido")
        self.assertEqual(self.entrada.responsavel_id, self.usuario.pk)
        self.assertIsNone(self.entrada.parcela_id)
        self.dados_pagamento = {
            "parcela": self.primeira.pk, "valor": "200.00", "forma_pagamento": "pix",
            "chave_idempotencia": str(uuid4()),
        }

    def executar_fluxo(self):
        self.criar_venda()
        resposta = self.client.post(reverse("pagamento-list"), self.dados_pagamento, format="json")
        self.assertEqual(resposta.status_code, 201, resposta.data)
        self.pagamento = Pagamento.objects.get(pk=resposta.data["id"])
        self.assertEqual(self.pagamento.venda_id, self.venda.pk)
        self.assertEqual(self.pagamento.parcela_id, self.primeira.pk)
        self.assertEqual(self.pagamento.responsavel_id, self.usuario.pk)
        self.assertEqual(self.pagamento.tipo, "parcela")
        self.assertEqual(self.pagamento.valor, Decimal("200.00"))
        self.assertEqual(self.pagamento.forma_pagamento, "pix")
        self.assertEqual(self.pagamento.status, "valido")
        self.conferir_saldos()

    def conferir_saldos(self):
        resumo = self.consultar("cliente-resumo-financeiro", self.cliente.pk)
        self.assertEqual(resumo, {
            "total_compras": "2400.00", "total_entradas_recebidas": "400.00",
            "total_pago_parcelas": "200.00", "total_efetivamente_pago": "600.00",
            "saldo_devedor": "1800.00", "saldo_entrada_estornada": "0.00",
            "parcelas_pendentes": 4, "parcelas_vencidas": 0, "parcelas_quitadas": 0,
        })
        self.assertEqual(Decimal(resumo["total_compras"])
                         - Decimal(resumo["total_entradas_recebidas"])
                         - Decimal(resumo["total_pago_parcelas"]), Decimal(resumo["saldo_devedor"]))
        parcelas = list(self.venda.parcelas.order_by("numero"))
        self.assertEqual([p.valor_pago for p in parcelas],
                         [Decimal("200.00")] + [Decimal("0.00")] * 3)
        self.assertEqual([p.saldo_restante for p in parcelas],
                         [Decimal("300.00")] + [Decimal("500.00")] * 3)
        self.assertEqual([p.status for p in parcelas], ["parcial"] + ["pendente"] * 3)
        self.assertTrue(all(p.data_quitacao is None for p in parcelas))
        self.assertEqual(sum((p.saldo_restante for p in parcelas), Decimal("0.00")),
                         Decimal(resumo["saldo_devedor"]))
        self.assertEqual(Venda.objects.count(), 1)
        self.assertEqual(ItemVenda.objects.count(), 1)
        self.assertEqual(Parcela.objects.count(), 4)
        self.assertEqual(Pagamento.objects.count(), 2)
        self.assertEqual(self.venda.pagamentos.filter(tipo="entrada").count(), 1)
        self.assertEqual(self.primeira.pagamentos.get().pk, self.pagamento.pk)

    def retrato_financeiro(self):
        # Inclui todos os campos para detectar também alterações de lançamentos existentes.
        return {modelo._meta.label: list(modelo.objects.order_by("pk").values())
                for modelo in (Venda, ItemVenda, Parcela, Pagamento)}

    def test_fluxo_completo_e_historico_consistente_nas_apis(self):
        self.executar_fluxo()
        venda = self.consultar("venda-detail", self.venda.pk)
        self.assertEqual(venda["cliente"], self.cliente.pk)
        self.assertEqual(venda["valor_total"], "2400.00")
        self.assertEqual(venda["valor_entrada"], "400.00")
        self.assertEqual(venda["valor_financiado"], "2000.00")
        self.assertEqual(len(venda["itens"]), 1)
        vendas = self.consultar("venda-list", parametros={"cliente": self.cliente.pk})
        self.assertEqual(vendas["count"], 1)
        self.assertEqual(vendas["results"], [venda])
        parcelas = self.consultar("parcela-list", parametros={"venda": self.venda.pk})
        vinculadas = self.consultar("venda-parcelas", self.venda.pk)
        self.assertEqual(parcelas["count"], 4)
        self.assertEqual(vinculadas["count"], 4)
        self.assertEqual(parcelas["results"], vinculadas["results"])
        self.assertEqual(parcelas["results"], venda["parcelas"])
        for indice, parcela in enumerate(parcelas["results"]):
            self.assertEqual(parcela["venda"], self.venda.pk)
            self.assertEqual(parcela["cliente"], self.cliente.pk)
            self.assertEqual(parcela["valor_original"], "500.00")
            self.assertEqual(parcela["valor_pago"], "200.00" if indice == 0 else "0.00")
            self.assertEqual(parcela["saldo_restante"], "300.00" if indice == 0 else "500.00")
            self.assertEqual(parcela, self.consultar("parcela-detail", parcela["id"]))
        historico = self.consultar("pagamento-list", parametros={"venda": self.venda.pk})
        self.assertEqual(historico["count"], 2)
        self.assertEqual({p["id"] for p in historico["results"]},
                         {self.entrada.pk, self.pagamento.pk})
        for pagamento in historico["results"]:
            self.assertEqual(pagamento["cliente"], self.cliente.pk)
            self.assertEqual(pagamento["venda"], self.venda.pk)
            self.assertEqual(pagamento["status"], "valido")
            self.assertEqual(pagamento, self.consultar("pagamento-detail", pagamento["id"]))
        self.assertEqual(sum((Decimal(p["valor"]) for p in historico["results"]),
                             Decimal("0.00")), Decimal("600.00"))

    def conferir_replay(self, endpoint, dados, identificador):
        antes = self.retrato_financeiro()
        resposta = self.client.post(reverse(endpoint), dados, format="json")
        self.assertEqual(resposta.status_code, 201, resposta.data)
        self.assertEqual(resposta.data["id"], identificador)
        self.assertEqual(self.retrato_financeiro(), antes)
        self.conferir_saldos()

    def test_repetir_venda_nao_duplica_entrada_itens_ou_parcelas(self):
        self.executar_fluxo()
        self.conferir_replay("venda-list", self.dados_venda, self.venda.pk)

    def test_repetir_pagamento_nao_duplica_recebimento(self):
        self.executar_fluxo()
        self.conferir_replay("pagamento-list", self.dados_pagamento, self.pagamento.pk)

    def conferir_pagamento_recusado(self, valor):
        self.executar_fluxo()
        antes = self.retrato_financeiro()
        chave = str(uuid4())
        resposta = self.client.post(reverse("pagamento-list"), {
            **self.dados_pagamento, "valor": valor, "chave_idempotencia": chave,
        }, format="json")
        self.assertEqual(resposta.status_code, 400, resposta.data)
        self.assertIn("valor", resposta.data)
        self.assertFalse(Pagamento.objects.filter(chave_idempotencia=chave).exists())
        self.assertEqual(self.retrato_financeiro(), antes)
        self.conferir_saldos()

    def test_pagamento_acima_do_saldo_nao_deixa_lancamentos_parciais(self):
        self.conferir_pagamento_recusado("400.00")

    def test_pagamento_zero_nao_deixa_lancamentos_parciais(self):
        self.conferir_pagamento_recusado("0.00")

    def test_pagamento_negativo_nao_deixa_lancamentos_parciais(self):
        self.conferir_pagamento_recusado("-200.00")

    def conferir_escritas_bloqueadas(self, cliente):
        antes = self.retrato_financeiro()
        for endpoint, dados in (("venda-list", self.dados_venda),
                                ("pagamento-list", self.dados_pagamento)):
            with self.subTest(endpoint=endpoint):
                resposta = cliente.post(reverse(endpoint), {
                    **dados, "chave_idempotencia": str(uuid4()),
                }, format="json")
                self.assertEqual(resposta.status_code, 403, resposta.data)
                self.assertEqual(self.retrato_financeiro(), antes)
                self.conferir_saldos()

    def test_sem_sessao_nao_cria_venda_ou_pagamento(self):
        self.executar_fluxo()
        self.conferir_escritas_bloqueadas(APIClient(enforce_csrf_checks=True))

    def test_sessao_sem_token_csrf_nao_cria_venda_ou_pagamento(self):
        self.executar_fluxo()
        sem_csrf = APIClient(enforce_csrf_checks=True)
        sem_csrf.force_login(self.usuario)
        self.conferir_escritas_bloqueadas(sem_csrf)
