import getpass
import os

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.core.validators import validate_email
from django.db import IntegrityError, transaction

from accounts.models import Profile
from companies.models import Company


PASSWORD_ENV_VAR = "BAR_SAAS_OWNER_PASSWORD"


class Command(BaseCommand):
    help = "Cria uma nova empresa beta e seu usuário proprietário."

    def add_arguments(self, parser):
        parser.add_argument("--company", required=True, help="Nome da nova empresa.")
        parser.add_argument("--username", required=True, help="Usuário do proprietário.")
        parser.add_argument("--email", required=True, help="E-mail do proprietário.")
        parser.add_argument("--document", help="Documento da empresa.")
        parser.add_argument("--phone", help="Telefone da empresa.")
        parser.add_argument(
            "--noinput",
            "--no-input",
            action="store_true",
            dest="noinput",
            help=(
                f"Não solicita senha no terminal; exige a variável {PASSWORD_ENV_VAR}."
            ),
        )

    def handle(self, *args, **options):
        company_name = options["company"].strip()
        username = options["username"].strip()
        email = get_user_model().objects.normalize_email(options["email"].strip())
        document = self._optional_value(options.get("document"))
        phone = self._optional_value(options.get("phone"))

        if not company_name:
            raise CommandError("O nome da empresa não pode ficar vazio.")

        if not username:
            raise CommandError("O nome de usuário não pode ficar vazio.")

        try:
            validate_email(email)
        except ValidationError as exc:
            raise CommandError("Informe um e-mail válido para o proprietário.") from exc

        password = self._get_password(noinput=options["noinput"])
        owner_candidate = get_user_model()(username=username, email=email)

        try:
            validate_password(password, user=owner_candidate)
        except ValidationError as exc:
            messages = " ".join(exc.messages)
            raise CommandError(f"A senha não atende aos requisitos: {messages}") from exc

        try:
            with transaction.atomic():
                self._reject_duplicates(
                    company_name=company_name,
                    document=document,
                    username=username,
                    email=email,
                )

                company = Company.objects.create(
                    name=company_name,
                    document=document,
                    phone=phone,
                )
                owner = get_user_model().objects.create_user(
                    username=username,
                    email=email,
                    password=password,
                    is_staff=False,
                    is_superuser=False,
                )
                Profile.objects.create(
                    user=owner,
                    company=company,
                    role="owner",
                )
        except IntegrityError as exc:
            raise CommandError(
                "Não foi possível criar a empresa e o proprietário; "
                "verifique se os dados já existem."
            ) from exc

        self.stdout.write(
            self.style.SUCCESS(
                f'Empresa "{company.name}" e proprietário "{owner.username}" '
                "criados com sucesso."
            )
        )

    @staticmethod
    def _optional_value(value):
        if value is None:
            return None

        normalized = value.strip()
        return normalized or None

    def _get_password(self, *, noinput):
        password_from_environment = os.environ.get(PASSWORD_ENV_VAR)

        if password_from_environment is not None:
            if not password_from_environment:
                raise CommandError(f"A variável {PASSWORD_ENV_VAR} está vazia.")
            return password_from_environment

        if noinput:
            raise CommandError(
                f"Defina {PASSWORD_ENV_VAR} ao executar o comando com --noinput."
            )

        password = getpass.getpass("Senha do proprietário: ")
        confirmation = getpass.getpass("Confirme a senha: ")

        if password != confirmation:
            raise CommandError("As senhas informadas não coincidem.")

        if not password:
            raise CommandError("A senha não pode ficar vazia.")

        return password

    @staticmethod
    def _reject_duplicates(*, company_name, document, username, email):
        if Company.objects.filter(name__iexact=company_name).exists():
            raise CommandError("Já existe uma empresa com esse nome.")

        if document and Company.objects.filter(document__iexact=document).exists():
            raise CommandError("Já existe uma empresa com esse documento.")

        user_model = get_user_model()

        if user_model.objects.filter(username__iexact=username).exists():
            raise CommandError("Já existe um usuário com esse nome.")

        if user_model.objects.filter(email__iexact=email).exists():
            raise CommandError("Já existe um usuário com esse e-mail.")
