"""Profile saves and hash upgrades cannot restore passwords replaced by recovery."""

from unittest.mock import patch

from asgiref.sync import async_to_sync
from django.contrib.auth.hashers import make_password
from django.test import TestCase, override_settings

from testing.helpers import make_user

from .models import User


class PasswordWriteTests(TestCase):
    def setUp(self):
        self.user = make_user("password_writes")

    def test_stale_plain_profile_save_keeps_a_replacement_password(self):
        stale = User.objects.get(pk=self.user.pk)
        self.user.set_password("Replacement-password42!")
        self.user.save(update_fields=["password"])
        stale.first_name = "Updated"
        stale.save()
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, "Updated")
        self.assertTrue(self.user.check_password("Replacement-password42!"))

    def test_intentional_password_writes_persist_without_replaying_on_later_saves(self):
        self.user.set_password("Chosen-password42!")
        self.user.save()
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("Chosen-password42!"))
        self.user.set_unusable_password()
        self.user.save()
        self.user.refresh_from_db()
        self.assertFalse(self.user.has_usable_password())
        User.objects.filter(pk=self.user.pk).update(password=make_password("Replacement-password42!"))
        self.user.first_name = "Late write"
        self.user.save()
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("Replacement-password42!"))

    @override_settings(PASSWORD_HASHERS=[
        "django.contrib.auth.hashers.PBKDF2PasswordHasher", "django.contrib.auth.hashers.MD5PasswordHasher",
    ])
    def test_sync_and_async_password_checks_upgrade_the_hash(self):
        original = self.user.password
        for asynchronous in (False, True):
            with self.subTest(asynchronous=asynchronous):
                User.objects.filter(pk=self.user.pk).update(password=original)
                self.user.refresh_from_db()
                check = async_to_sync(self.user.acheck_password) if asynchronous else self.user.check_password
                self.assertTrue(check("pass1234"))
                self.user.refresh_from_db()
                self.assertTrue(self.user.password.startswith("pbkdf2_sha256$"))

    @override_settings(PASSWORD_HASHERS=[
        "django.contrib.auth.hashers.PBKDF2PasswordHasher", "django.contrib.auth.hashers.MD5PasswordHasher",
    ])
    def test_sync_and_async_hash_upgrades_cannot_overwrite_a_concurrent_replacement(self):
        original = self.user.password
        replacement = make_password("Replacement-password42!")

        def replace_before_upgrade(password):
            User.objects.filter(pk=self.user.pk).update(password=replacement)
            return make_password(password)

        for asynchronous in (False, True):
            with self.subTest(asynchronous=asynchronous):
                User.objects.filter(pk=self.user.pk).update(password=original)
                self.user.refresh_from_db()
                check = async_to_sync(self.user.acheck_password) if asynchronous else self.user.check_password
                with patch("accounts.models.make_password", side_effect=replace_before_upgrade):
                    self.assertFalse(check("pass1234"))
                self.user.refresh_from_db()
                self.assertEqual(self.user.password, replacement)
