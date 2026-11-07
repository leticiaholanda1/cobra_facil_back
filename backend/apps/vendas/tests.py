from datetime import date
from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APITestCase

from apps.clientes.models import Cliente
from apps.financeiro.models import Pagamento, Parcela
from apps.financeiro.services import estornar_pagamento, registrar_pagamento

from .models import ItemVenda, Venda
from .services import cancelar_venda, registrar_venda, vencimento_mensal


class VendaFixtureMixin:
    def setUp(self):
        super().setUp()
        self.user = get_user_model().objects.create_user(username="operador-vendas")
        self.cliente = Cliente.objects.create(nome="Ana", telefone="85999991234")

    def dados_venda(self, **kwargs):
        return {
            "cliente_id": self.cliente.pk,
            "itens": [{"descricao": "Geladeira", "quantidade": 1, "valor_unitario": "2400.00"}],
            "valor_entrada": "400.00", "forma_entrada": "pix", "quantidade_parcelas": 4,
            "primeiro_vencimento": date(2030, 1, 31), "usuario": self.user,
            "chave_idempotencia": uuid4(), **kwargs,
        }

    def venda(self, **kwargs):
        return registrar_venda(**self.dados_venda(**kwargs))

    def pagar(self, parcela, valor="100.00", **kwargs):
        return registrar_pagamento(**{
            "parcela_id": parcela.pk, "valor": valor, "forma_pagamento": "pix",
            "usuario": self.user, "chave_idempotencia": uuid4(), **kwargs,
        })


class VendaServiceTests(VendaFixtureMixin, TestCase):
    def test_venda_valida_itens_entrada_e_parcelas(self):
        venda = self.venda()
        self.assertEqual(venda.valor_financiado, Decimal("2000.00"))
        self.assertEqual(venda.itens.get().valor_total, Decimal("2400.00"))
        self.assertEqual(list(venda.parcelas.values_list("valor_original", flat=True)), [Decimal("500.00")] * 4)
        entrada = venda.pagamentos.get()
        self.assertEqual(entrada.tipo, "entrada")
        self.assertEqual(entrada.valor, Decimal("400.00"))
        self.assertIsNone(entrada.parcela_id)
        self.assertEqual(entrada.responsavel, self.user)

    def test_sem_cliente(self):
        with self.assertRaises(ValidationError):
            self.venda(cliente_id=None)
        self.assertFalse(Venda.objects.exists())

    def test_cliente_inativo(self):
        self.cliente.ativo = False
        self.cliente.save()
        with self.assertRaises(ValidationError):
            self.venda()

    def test_entrada_maior_que_total_e_negativa(self):
        for entrada in ("2400.01", "-0.01"):
            with self.subTest(entrada=entrada), self.assertRaises(ValidationError):
                self.venda(valor_entrada=entrada)

    def test_itens_invalidos(self):
        for itens in ([], [{"descricao": "", "quantidade": 1, "valor_unitario": "10.00"}],
                      [{"descricao": "TV", "quantidade": 0, "valor_unitario": "10.00"}],
                      [{"descricao": "TV", "quantidade": 1, "valor_unitario": "-10.00"}],
                      [{"descricao": "TV", "quantidade": 1, "valor_unitario": "0.00"}]):
            with self.subTest(itens=itens), self.assertRaises(ValidationError):
                self.venda(itens=itens)

    def test_total_divergente(self):
        with self.assertRaises(ValidationError):
            self.venda(valor_total="2399.99")

    def test_soma_multiplos_itens(self):
        venda = self.venda(itens=[
            {"descricao": "A", "quantidade": 2, "valor_unitario": "1000.00"},
            {"descricao": "B", "quantidade": 4, "valor_unitario": "100.00"},
        ], valor_total="2400.00")
        self.assertEqual(venda.valor_total, Decimal("2400.00"))
        self.assertEqual(venda.itens.count(), 2)

    def test_venda_a_vista(self):
        venda = self.venda(valor_entrada="2400.00", quantidade_parcelas=0, primeiro_vencimento=None)
        self.assertEqual(venda.valor_financiado, Decimal("0.00"))
        self.assertFalse(venda.parcelas.exists())
        self.assertEqual(venda.pagamentos.get().valor, Decimal("2400.00"))

    def test_plano_invalido(self):
        for changes in ({"quantidade_parcelas": 0}, {"quantidade_parcelas": -1},
                        {"primeiro_vencimento": None}, {"quantidade_parcelas": 1201},
                        {"valor_entrada": "2400.00"}, {"forma_entrada": None}):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                self.venda(**changes)

    def test_arredondamento_e_menor_centavo(self):
        venda = self.venda(itens=[{"descricao": "TV", "quantidade": 1, "valor_unitario": "100.00"}],
                           valor_entrada="0.00", forma_entrada=None, quantidade_parcelas=3)
        valores = list(venda.parcelas.values_list("valor_original", flat=True))
        self.assertEqual(valores, [Decimal("33.33"), Decimal("33.33"), Decimal("33.34")])
        self.assertEqual(sum(valores), venda.valor_financiado)
        with self.assertRaises(ValidationError):
            self.venda(itens=[{"descricao": "TV", "quantidade": 1, "valor_unitario": "0.02"}],
                       valor_entrada="0.00", forma_entrada=None, quantidade_parcelas=3)

    def test_datas_fevereiro_e_ancora_original(self):
        for year, feb_day in ((2028, 29), (2030, 28)):
            primeiro = date(year, 1, 31)
            self.assertEqual(vencimento_mensal(primeiro, 1), date(year, 2, feb_day))
            self.assertEqual(vencimento_mensal(primeiro, 2), date(year, 3, 31))
            self.assertEqual(vencimento_mensal(primeiro, 3), date(year, 4, 30))
        self.assertEqual(vencimento_mensal(date(2029, 12, 30), 1), date(2030, 1, 30))
        venda = self.venda()
        self.assertEqual(list(venda.parcelas.values_list("vencimento", flat=True)),
                         [date(2030, 1, 31), date(2030, 2, 28), date(2030, 3, 31), date(2030, 4, 30)])

    def test_idempotencia_venda_e_conflito(self):
        data = self.dados_venda()
        first = registrar_venda(**data)
        self.assertEqual(registrar_venda(**data).pk, first.pk)
        self.assertEqual(Venda.objects.count(), 1)
        self.assertEqual(Parcela.objects.count(), 4)
        self.assertEqual(Pagamento.objects.count(), 1)
        with self.assertRaises(ValidationError):
            registrar_venda(**{**data, "valor_entrada": "500.00"})

    def test_atomicidade_falha_na_geracao(self):
        with patch.object(Parcela, "save", side_effect=ValidationError("Falha simulada")):
            with self.assertRaises(ValidationError):
                self.venda()
        self.assertFalse(Venda.objects.exists())
        self.assertFalse(ItemVenda.objects.exists())
        self.assertFalse(Pagamento.objects.exists())

    def test_rejeita_float_e_fracoes_de_centavo(self):
        for valor in (1.5, "1.001", "NaN", "Infinity"):
            with self.subTest(valor=valor), self.assertRaises(ValidationError):
                self.venda(valor_entrada=valor)

    def test_cancelar_sem_recebimentos(self):
        venda = self.venda(valor_entrada="0.00", forma_entrada=None)
        cancelar_venda(venda_id=venda.pk, usuario=self.user, motivo="Venda incorreta")
        venda.refresh_from_db()
        self.assertEqual(venda.status, "cancelada")
        self.assertEqual(venda.cancelada_por, self.user)
        self.assertIsNotNone(venda.cancelada_em)
        self.assertEqual(venda.parcelas.count(), 4)
        self.assertEqual(cancelar_venda(venda_id=venda.pk, usuario=self.user, motivo="Venda incorreta").pk, venda.pk)

    def test_cancelamento_bloqueado_por_entrada(self):
        venda = self.venda()
        with self.assertRaises(ValidationError):
            cancelar_venda(venda_id=venda.pk, usuario=self.user, motivo="Erro")
        venda.refresh_from_db()
        self.assertEqual(venda.status, "ativa")

    def test_cancelamento_exige_estorno_de_todos_recebimentos(self):
        venda = self.venda()
        pagamento = self.pagar(venda.parcelas.first())
        estornar_pagamento(pagamento_id=venda.pagamentos.get(tipo="entrada").pk, usuario=self.user, motivo="Correção")
        with self.assertRaises(ValidationError):
            cancelar_venda(venda_id=venda.pk, usuario=self.user, motivo="Erro")
        estornar_pagamento(pagamento_id=pagamento.pk, usuario=self.user, motivo="Correção")
        cancelar_venda(venda_id=venda.pk, usuario=self.user, motivo="Erro")
        self.assertEqual(venda.pagamentos.count(), 2)
        self.assertEqual(venda.parcelas.count(), 4)

    def test_historico_protegido_por_cliente(self):
        self.venda()
        from django.db.models.deletion import ProtectedError
        with self.assertRaises(ProtectedError):
            self.cliente.delete()


class VendaAPITests(VendaFixtureMixin, APITestCase):
    def setUp(self):
        super().setUp()
        self.client.force_authenticate(self.user)
        self.url = reverse("venda-list")

    def payload(self, **changes):
        data = self.dados_venda()
        data.pop("usuario")
        data["cliente"] = data.pop("cliente_id")
        return {**data, **changes}

    def test_criar_listar_consultar_parcelas(self):
        response = self.client.post(self.url, self.payload(), format="json")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["valor_financiado"], "2000.00")
        self.assertEqual(len(response.data["parcelas"]), 4)
        pk = response.data["id"]
        self.assertEqual(self.client.get(reverse("venda-detail", args=[pk])).status_code, 200)
        self.assertEqual(self.client.get(self.url).data["count"], 1)
        self.assertEqual(self.client.get(reverse("venda-parcelas", args=[pk])).data["count"], 4)

    def test_campos_derivados_e_cliente_obrigatorio(self):
        for field in ("valor_financiado", "status", "responsavel", "criado_em"):
            response = self.client.post(self.url, self.payload(**{field: "123"}), format="json")
            self.assertEqual(response.status_code, 400)
            self.assertIn(field, response.data)
        data = self.payload()
        data.pop("cliente")
        self.assertEqual(self.client.post(self.url, data, format="json").status_code, 400)

    def test_idempotencia_api(self):
        data = self.payload()
        one = self.client.post(self.url, data, format="json")
        two = self.client.post(self.url, data, format="json")
        self.assertEqual(one.status_code, 201)
        self.assertEqual(two.data["id"], one.data["id"])
        self.assertEqual(Venda.objects.count(), 1)

    def test_cancelar_api_e_sem_edicao_ou_delete(self):
        venda = self.venda(valor_entrada="0.00", forma_entrada=None)
        url = reverse("venda-detail", args=[venda.pk])
        for method in ("put", "patch", "delete"):
            self.assertEqual(getattr(self.client, method)(url, {}, format="json").status_code, 405)
        response = self.client.post(reverse("venda-cancelar", args=[venda.pk]), {"motivo": "Erro"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], "cancelada")

    def test_filtros_cliente_periodo_status(self):
        self.venda(data_venda=date(2030, 1, 10))
        self.venda(data_venda=date(2030, 2, 10))
        response = self.client.get(self.url, {"cliente": self.cliente.pk, "data_inicio": "2030-02-01", "status": "ativa"})
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(self.client.get(self.url, {"status": "invalido"}).status_code, 400)
        self.assertEqual(self.client.get(self.url, {"data_inicio": "abc"}).status_code, 400)

    def test_permissoes_e_sessao(self):
        self.client.force_authenticate(user=None)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(self.url).status_code, 200)
