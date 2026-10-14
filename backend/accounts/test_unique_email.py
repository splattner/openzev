"""#1005: an email address identifies exactly one account, whatever its case."""

from django.contrib.auth.hashers import make_password
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase
from rest_framework.test import APIClient

from accounts.models import User, UserRole
from testing.helpers import authenticate, make_user


class UniqueEmailConstraintTests(TestCase):
    def test_a_second_account_cannot_take_the_address_in_another_case(self):
        User.objects.create_user(username="first", email="Anna@Example.com")
        with self.assertRaises(IntegrityError), transaction.atomic():
            User.objects.create_user(username="second", email="anna@example.com")

    def test_accounts_without_an_address_do_not_collide(self):
        User.objects.create_user(username="blank_one", email="")
        User.objects.create_user(username="blank_two", email="")
        self.assertEqual(User.objects.filter(email="").count(), 2)

    def test_model_validation_names_the_problem(self):
        User.objects.create_user(username="holder", email="taken@example.com")
        clash = User(username="clash", email="TAKEN@example.com")
        with self.assertRaises(Exception) as caught:
            clash.validate_constraints()
        self.assertIn("already exists", str(caught.exception))


class AdminAccountEmailTests(TestCase):
    def setUp(self):
        self.admin = make_user("ue_admin", UserRole.ADMIN)
        self.client = APIClient()
        authenticate(self.client, self.admin)
        self.other = make_user("ue_other", UserRole.USER)

    def test_creating_an_account_with_a_taken_address_is_a_validation_error(self):
        response = self.client.post(
            "/api/v1/auth/users/",
            {"username": "newbie", "email": self.other.email.upper(), "first_name": "N", "last_name": "B"},
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("email", response.json())
        self.assertFalse(User.objects.filter(username="newbie").exists())

    def test_moving_an_account_to_a_taken_address_is_a_validation_error(self):
        user = make_user("ue_mover", UserRole.USER)
        response = self.client.patch(f"/api/v1/auth/users/{user.pk}/", {"email": self.other.email}, format="json")
        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("email", response.json())

    def test_saving_an_account_with_its_own_address_still_works(self):
        response = self.client.patch(
            f"/api/v1/auth/users/{self.other.pk}/",
            {"email": self.other.email, "first_name": "Same"}, format="json",
        )
        self.assertEqual(response.status_code, 200, response.content)


class MergeDuplicateEmailsMigrationTests(TransactionTestCase):
    """accounts.0026 folds accounts that share an address before 0027 forbids it."""

    BEFORE = [("accounts", "0025_backfill_independent_login_required"), ("zev", "0043_report_invalid_invoice_prefixes")]
    AFTER = [("accounts", "0026_merge_duplicate_account_emails")]

    def migrate(self, targets):
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(targets)
        return executor.loader.project_state(targets).apps

    def setUp(self):
        self.tearDown()

    def tearDown(self):
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(executor.loader.graph.leaf_nodes())

    def _world(self):
        old = self.migrate(self.BEFORE)
        User = old.get_model("accounts", "User")
        Zev = old.get_model("zev", "Zev")
        Party = old.get_model("zev", "Party")
        Participant = old.get_model("zev", "Participant")
        zev = Zev.objects.create(name="Merge ZEV", zev_type="vzev", invoice_prefix="M")
        # The common case: one participant-only account per row, same person.
        accounts = [
            User.objects.create(username=f"p{i}", email="Anna@example.com" if i % 2 else "anna@example.com",
                                password=make_password(None))
            for i in range(3)
        ]
        participants = []
        for account in accounts:
            party = Party.objects.create(zev=zev, last_name="Anna", email=account.email)
            participants.append(Participant.objects.create(zev=zev, party=party, user=account, valid_from="2026-01-01"))
        # A real login that shares the address with a participant-only account.
        login = User.objects.create(username="login", email="shared@example.com", password=make_password("pw-12345"))
        bare = User.objects.create(username="bare", email="SHARED@example.com", password=make_password(None))
        party = Party.objects.create(zev=zev, last_name="Shared", email="shared@example.com")
        shared_row = Participant.objects.create(zev=zev, party=party, user=bare, valid_from="2026-01-01")
        # Two logins of their own: neither can be folded into the other.
        first = User.objects.create(username="first", email="two@example.com", password=make_password("pw-12345"))
        second = User.objects.create(username="second", email="TWO@example.com", password=make_password("pw-12345"))
        return {
            "participants": participants, "shared_row": shared_row, "login": login, "bare": bare,
            "first": first, "second": second, "oldest": accounts[0],
        }, self.migrate(self.AFTER)

    def test_participant_only_duplicates_collapse_onto_one_account(self):
        world, new = self._world()
        User, Participant = new.get_model("accounts", "User"), new.get_model("zev", "Participant")
        self.assertEqual(User.objects.filter(email__iexact="anna@example.com").count(), 1)
        keeper = User.objects.get(email__iexact="anna@example.com")
        self.assertEqual(keeper.pk, world["oldest"].pk)
        for participant in world["participants"]:
            self.assertEqual(Participant.objects.get(pk=participant.pk).user_id, keeper.pk)

    def test_an_account_with_a_login_outranks_a_participant_only_one(self):
        world, new = self._world()
        User, Participant = new.get_model("accounts", "User"), new.get_model("zev", "Participant")
        self.assertTrue(User.objects.filter(pk=world["login"].pk, email="shared@example.com").exists())
        self.assertFalse(User.objects.filter(pk=world["bare"].pk).exists())
        self.assertEqual(Participant.objects.get(pk=world["shared_row"].pk).user_id, world["login"].pk)

    def test_two_logins_are_both_kept_but_only_one_keeps_the_address(self):
        world, new = self._world()
        User = new.get_model("accounts", "User")
        self.assertEqual(User.objects.filter(email__iexact="two@example.com").count(), 1)
        self.assertEqual(User.objects.filter(pk__in=[world["first"].pk, world["second"].pk]).count(), 2)
        self.assertEqual(User.objects.get(pk=world["first"].pk).email, "two@example.com")
        self.assertEqual(User.objects.get(pk=world["second"].pk).email, "")

    def test_the_constraint_holds_afterwards(self):
        self._world()
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(executor.loader.graph.leaf_nodes())
        User.objects.create_user(username="fresh", email="fresh@example.com")
        with self.assertRaises(IntegrityError), transaction.atomic():
            User.objects.create_user(username="fresher", email="FRESH@example.com")
