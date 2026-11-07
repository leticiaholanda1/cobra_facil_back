from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APITestCase

from .forms import ClienteAdminForm
from .models import Cliente


class ClienteModelTests(TestCase):
    def test_cadastro_valido_e_metadados(self):
        cliente = Cliente.objects.create(nome=" Ana Silva ", telefone="(85) 99999-1234")
        self.assertEqual(str(cliente), "Ana Silva")
        self.assertIsNone(cliente.cpf)
        self.assertTrue(cliente.ativo)
        self.assertIsNotNone(cliente.criado_em)
        self.assertIsNotNone(cliente.atualizado_em)
        self.assertEqual(Cliente._meta.verbose_name_plural, "clientes")

    def test_campos_obrigatorios(self):
        for field, value in (("nome", ""), ("nome", "   "), ("telefone", "")):
            with self.subTest(field=field, value=value):
                data = {"nome": "Ana", "telefone": "85999991234", field: value}
                with self.assertRaises(ValidationError) as error:
                    Cliente.objects.create(**data)
                self.assertIn(field, error.exception.message_dict)

    def test_normalizacao_cpf_cep_estado(self):
        cliente = Cliente.objects.create(
            nome="Ana", telefone="85999991234", cpf="529.982.247-25",
            cep="60000-000", estado="ce",
        )
        cliente.refresh_from_db()
        self.assertEqual(cliente.cpf, "52998224725")
        self.assertEqual(cliente.cep, "60000000")
        self.assertEqual(cliente.estado, "CE")

    def test_cpfs_invalidos(self):
        for cpf in ("11111111111", "52998224724", "123", "abc52998224725", "00000000000"):
            with self.subTest(cpf=cpf), self.assertRaises(ValidationError):
                Cliente.objects.create(nome="Ana", telefone="85999991234", cpf=cpf)

    def test_cpf_duplicado_normalizado(self):
        Cliente.objects.create(nome="Ana", telefone="85999991234", cpf="52998224725")
        with self.assertRaises(ValidationError):
            Cliente.objects.create(nome="Bia", telefone="85999991234", cpf="529.982.247-25")

    def test_unicidade_cpf_no_banco(self):
        Cliente.objects.create(nome="Ana", telefone="85999991234", cpf="52998224725")
        with self.assertRaises(IntegrityError), transaction.atomic():
            Cliente.objects.bulk_create([
                Cliente(nome="Bia", telefone="85999991234", cpf="52998224725"),
            ])

    def test_multiplos_clientes_sem_cpf(self):
        for cpf in (None, "", "   "):
            cliente = Cliente.objects.create(nome="Ana", telefone="85999991234", cpf=cpf)
            self.assertIsNone(cliente.cpf)
        self.assertEqual(Cliente.objects.filter(cpf__isnull=True).count(), 3)

    def test_telefone_cep_estado_invalidos(self):
        for field, value in (
            ("telefone", "abc85999991234"), ("telefone", "123"),
            ("whatsapp", "abc"), ("cep", "123"), ("cep", "abc60000000"),
            ("estado", "12"),
        ):
            with self.subTest(field=field), self.assertRaises(ValidationError):
                Cliente.objects.create(**{"nome": "Ana", "telefone": "85999991234", field: value})


class ClienteAPITests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="operador", password="teste-seguro")
        self.client.force_authenticate(self.user)
        self.url = reverse("cliente-list")
        self.data = {"nome": "Ana Silva", "telefone": "85999991234"}

    def create_cliente(self, **kwargs):
        return Cliente.objects.create(**{**self.data, **kwargs})

    def test_cadastro_consulta_e_json(self):
        response = self.client.post(self.url, self.data, format="json")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response["Content-Type"], "application/json")
        detail = self.client.get(reverse("cliente-detail", args=[response.data["id"]]))
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.data["nome"], self.data["nome"])

    def test_acesso_nao_autenticado_bloqueado(self):
        cliente = self.create_cliente()
        detail = reverse("cliente-detail", args=[cliente.pk])
        self.client.force_authenticate(user=None)
        for method, url in (("get", self.url), ("post", self.url), ("get", detail),
                            ("patch", detail), ("put", detail), ("delete", detail)):
            with self.subTest(method=method, url=url):
                self.assertEqual(getattr(self.client, method)(url).status_code, 403)

    def test_autenticacao_por_sessao(self):
        self.client.force_authenticate(user=None)
        self.assertTrue(self.client.login(username="operador", password="teste-seguro"))
        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_campos_obrigatorios_e_erros_estruturados(self):
        for field, value in (("nome", ""), ("nome", "   "), ("telefone", ""), ("telefone", "abc")):
            with self.subTest(field=field, value=value):
                response = self.client.post(self.url, {**self.data, field: value}, format="json")
                self.assertEqual(response.status_code, 400)
                self.assertIn(field, response.data)
        for field in ("nome", "telefone"):
            data = self.data.copy()
            data.pop(field)
            self.assertEqual(self.client.post(self.url, data).status_code, 400)

    def test_cpf_valido_normalizado_e_duplicado(self):
        response = self.client.post(self.url, {
            **self.data, "cpf": "529.982.247-25", "cep": "60000-000",
        })
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["cpf"], "52998224725")
        self.assertEqual(response.data["cep"], "60000000")
        for cpf in ("52998224725", "529.982.247-25"):
            response = self.client.post(self.url, {**self.data, "cpf": cpf})
            self.assertEqual(response.status_code, 400)
            self.assertIn("cpf", response.data)

    def test_cpf_invalido(self):
        for cpf in ("52998224724", "11111111111", "123", "abc52998224725"):
            with self.subTest(cpf=cpf):
                response = self.client.post(self.url, {**self.data, "cpf": cpf})
                self.assertEqual(response.status_code, 400)
                self.assertIn("cpf", response.data)

    def test_cep_invalido(self):
        response = self.client.post(self.url, {**self.data, "cep": "abc60000000"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("cep", response.data)

    def test_multiplos_sem_cpf(self):
        for extra in ({}, {"cpf": ""}, {"cpf": None}, {"cpf": "  "}):
            response = self.client.post(self.url, {**self.data, **extra}, format="json")
            self.assertEqual(response.status_code, 201)
            self.assertIsNone(response.data["cpf"])

    def test_atualizacao_patch_put_e_cpf_proprio(self):
        cliente = self.create_cliente(cpf="52998224725")
        url = reverse("cliente-detail", args=[cliente.pk])
        response = self.client.patch(url, {"nome": "Ana Souza", "cpf": "529.982.247-25"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["nome"], "Ana Souza")
        response = self.client.put(url, {"nome": "Ana Lima", "telefone": "85988881234"})
        self.assertEqual(response.status_code, 200)
        cliente.refresh_from_db()
        self.assertEqual(cliente.nome, "Ana Lima")
        self.assertEqual(cliente.telefone, "85988881234")

    def test_limpar_cpf(self):
        cliente = self.create_cliente(cpf="52998224725")
        url = reverse("cliente-detail", args=[cliente.pk])
        self.assertEqual(self.client.patch(url, {"cpf": ""}).status_code, 200)
        cliente.refresh_from_db()
        self.assertIsNone(cliente.cpf)

    def test_datas_e_id_somente_leitura(self):
        response = self.client.post(self.url, {
            **self.data, "id": 9999, "criado_em": "2000-01-01T00:00:00Z",
            "atualizado_em": "2000-01-01T00:00:00Z",
        })
        self.assertEqual(response.status_code, 201)
        self.assertNotEqual(response.data["id"], 9999)
        cliente = Cliente.objects.get(pk=response.data["id"])
        self.assertNotEqual(cliente.criado_em.year, 2000)
        self.assertNotEqual(cliente.atualizado_em.year, 2000)

    def test_desativacao_sem_exclusao_e_consulta_inativo(self):
        cliente = self.create_cliente()
        url = reverse("cliente-detail", args=[cliente.pk])
        self.assertEqual(self.client.delete(url).status_code, 204)
        cliente.refresh_from_db()
        self.assertFalse(cliente.ativo)
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(self.client.delete(url).status_code, 204)

    def test_pesquisa_nome_cpf_telefone(self):
        cliente = self.create_cliente(cpf="52998224725")
        self.create_cliente(nome="Bruno", telefone="11912345678")
        for term in ("sil", "529982", "8599999"):
            with self.subTest(term=term):
                response = self.client.get(self.url, {"search": term})
                self.assertEqual(response.data["count"], 1)
                self.assertEqual(response.data["results"][0]["id"], cliente.pk)

    def test_filtro_ativo(self):
        self.create_cliente()
        self.create_cliente(nome="Bia", ativo=False)
        for value, expected in (("true", True), ("false", False), ("1", True), ("0", False)):
            response = self.client.get(self.url, {"ativo": value})
            self.assertEqual(response.data["count"], 1)
            self.assertEqual(response.data["results"][0]["ativo"], expected)
        self.assertEqual(self.client.get(self.url, {"ativo": "inválido"}).status_code, 400)
        self.assertEqual(self.client.get(self.url).data["count"], 2)

    def test_ordenacao(self):
        first = self.create_cliente(nome="Bruno")
        second = self.create_cliente(nome="Ana")
        for ordering, expected in (("nome", second.pk), ("-nome", first.pk),
                                   ("criado_em", first.pk), ("-criado_em", second.pk)):
            response = self.client.get(self.url, {"ordering": ordering})
            self.assertEqual(response.data["results"][0]["id"], expected)

    def test_paginacao(self):
        Cliente.objects.bulk_create([
            Cliente(nome=f"Cliente {i:02}", telefone="85999991234") for i in range(26)
        ])
        response = self.client.get(self.url)
        self.assertEqual(set(response.data), {"count", "next", "previous", "results"})
        self.assertEqual(response.data["count"], 26)
        self.assertEqual(len(response.data["results"]), 25)
        self.assertIsNotNone(response.data["next"])
        page2 = self.client.get(self.url, {"page": 2})
        self.assertEqual(len(page2.data["results"]), 1)


class ClienteAdminTests(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_superuser(
            username="admin", email="admin@example.com", password="teste-seguro",
        )
        self.client.force_login(user)
        self.data = {"nome": "Ana", "telefone": "85999991234", "ativo": True}

    def test_registro_paginas_e_sem_exclusao(self):
        self.assertIn(Cliente, admin.site._registry)
        self.assertEqual(self.client.get(reverse("admin:clientes_cliente_changelist")).status_code, 200)
        self.assertEqual(self.client.get(reverse("admin:clientes_cliente_add")).status_code, 200)
        model_admin = admin.site._registry[Cliente]
        self.assertFalse(model_admin.has_delete_permission(None))
        self.assertIn("criado_em", model_admin.readonly_fields)
        self.assertIn("atualizado_em", model_admin.readonly_fields)

    def test_formulario_normaliza_e_valida_duplicidade(self):
        data = {**self.data, "cpf": "529.982.247-25", "cep": "60000-000"}
        form = ClienteAdminForm(data=data)
        self.assertTrue(form.is_valid(), form.errors)
        cliente = form.save()
        self.assertEqual(cliente.cpf, "52998224725")
        self.assertEqual(cliente.cep, "60000000")
        duplicate = ClienteAdminForm(data=data)
        self.assertFalse(duplicate.is_valid())
        self.assertIn("cpf", duplicate.errors)

    def test_formulario_rejeita_campos_invalidos(self):
        for field, value in (("nome", "  "), ("cpf", "11111111111"),
                             ("telefone", "123"), ("cep", "123")):
            with self.subTest(field=field):
                form = ClienteAdminForm(data={**self.data, field: value})
                self.assertFalse(form.is_valid())
                self.assertIn(field, form.errors)

    def test_cadastrar_pesquisar_editar_desativar(self):
        response = self.client.post(reverse("admin:clientes_cliente_add"), self.data)
        self.assertEqual(response.status_code, 302)
        cliente = Cliente.objects.get()
        response = self.client.get(reverse("admin:clientes_cliente_changelist"), {"q": "An"})
        self.assertContains(response, "Ana")
        data = {**self.data, "nome": "Ana Silva"}
        data.pop("ativo")
        response = self.client.post(reverse("admin:clientes_cliente_change", args=[cliente.pk]), data)
        self.assertEqual(response.status_code, 302)
        cliente.refresh_from_db()
        self.assertEqual(cliente.nome, "Ana Silva")
        self.assertFalse(cliente.ativo)
