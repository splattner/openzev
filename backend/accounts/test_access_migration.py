"""accounts.0020 (#761): the 2FA role list becomes one switch; owners keep self-setup."""

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

BEFORE = [("accounts", "0019_user_session_version")]
AFTER = [("accounts", "0020_access_grants_accounts")]


class AccessGrantsAccountsMigrationTests(TransactionTestCase):
    def migrate(self, targets):
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(targets)
        return executor.loader.project_state(targets).apps

    def tearDown(self):
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(executor.loader.graph.leaf_nodes())

    def _world(self, roles):
        old = self.migrate(BEFORE)
        old.get_model("accounts", "AppSettings").objects.update_or_create(
            pk=1, defaults={"mfa_required_roles": roles, "singleton_enforcer": True},
        )
        User = old.get_model("accounts", "User")
        User.objects.create(username="mig_owner", email="o@example.com", role="zev_owner")
        User.objects.create(username="mig_tenant", email="t@example.com", role="participant")
        return self.migrate(AFTER)

    def test_a_role_list_turns_the_switch_on_and_restarts_the_grace_period(self):
        new = self._world(["admin"])
        settings_row = new.get_model("accounts", "AppSettings").objects.get(pk=1)
        self.assertIs(settings_row.mfa_required, True)
        self.assertIsNotNone(settings_row.mfa_policy_changed_at)

    def test_an_empty_list_leaves_it_off(self):
        new = self._world([])
        settings_row = new.get_model("accounts", "AppSettings").objects.get(pk=1)
        self.assertIs(settings_row.mfa_required, False)
        self.assertIsNone(settings_row.mfa_policy_changed_at)

    def test_existing_owner_accounts_may_still_create_a_zev(self):
        new = self._world([])
        User = new.get_model("accounts", "User")
        self.assertIs(User.objects.get(username="mig_owner").may_create_zev, True)
        self.assertIs(User.objects.get(username="mig_tenant").may_create_zev, False)
