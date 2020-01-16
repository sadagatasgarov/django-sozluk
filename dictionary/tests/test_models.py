import datetime
import time

from decimal import Decimal
from unittest import mock

from django.db import IntegrityError
from django.shortcuts import reverse
from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from ..models import (Author, Entry, Topic, Message, Category, Memento, UserVerification, EntryFavorites, Conversation,
                      GeneralReport, TopicFollowing)


class AuthorModelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.author = Author.objects.create(username="user", email="0")
        cls.topic = Topic.objects.create_topic("test_topic")
        cls.entry_base = dict(topic=cls.topic, author=cls.author)

    def test_profile_entry_counts(self):
        Entry.objects.create(**self.entry_base)  # created now (today)
        # dates to be mocked for auto now add field 'date_created'
        mock_60 = timezone.now() - datetime.timedelta(days=35)  # created more than 1 months ago
        mock_30 = timezone.now() - datetime.timedelta(days=25)  # created in 1 month period
        mock_14 = timezone.now() - datetime.timedelta(days=12)  # created in 2 weeks period
        mock_7 = timezone.now() - datetime.timedelta(days=5)  # created in 1 week period
        mock_1 = timezone.now() - datetime.timedelta(hours=20)  # created today

        with mock.patch('django.utils.timezone.now') as mock_now:
            mock_now.return_value = mock_60
            Entry.objects.create(**self.entry_base)
            mock_now.return_value = mock_30
            Entry.objects.create(**self.entry_base)
            mock_now.return_value = mock_14
            Entry.objects.create(**self.entry_base)
            mock_now.return_value = mock_7
            Entry.objects.create(**self.entry_base)
            mock_now.return_value = mock_1
            Entry.objects.create(**self.entry_base)

        self.assertEqual(self.author.entry_count, 6)
        self.assertEqual(self.author.entry_count_day, 2)
        self.assertEqual(self.author.entry_count_month, 5)
        self.assertEqual(self.author.entry_count_week, 3)

    def test_last_entry_date(self):
        Entry.objects.create(**self.entry_base, is_draft=True)
        self.assertIsNone(self.author.last_entry_date)
        entry = Entry.objects.create(**self.entry_base)
        self.assertEqual(self.author.last_entry_date, entry.date_created)

    def test_followers(self):
        self.assertEqual(self.author.followers.count(), 0)  # no follower supplied yet
        follower = Author.objects.create(username="1", email="1")
        some_other_follower = Author.objects.create(username="2", email="2")
        follower.following.add(self.author)
        some_other_follower.following.add(self.author)
        self.assertIn(follower, self.author.followers)
        self.assertEqual(self.author.followers.count(), 2)

    def test_novice_list_join_retreat(self):
        """
        10 published entries needed in order an user to be in the novice list, if the number of entries drop to < 10
        user is removed from novice list
        """

        # Initial status
        self.assertEqual(self.author.application_status, Author.ON_HOLD)
        self.assertIsNone(self.author.application_date)

        # Add NINE entries
        for _ in range(9):
            Entry.objects.create(**self.entry_base)

        # add an entry which is a draft
        Entry.objects.create(**self.entry_base, is_draft=True)

        # There are 10 PUBLISHED entries required, 9 present, so everything should be the same
        self.assertEqual(self.author.application_status, Author.ON_HOLD)
        self.assertIsNone(self.author.application_date)

        # add 10th entry (user joins the novice list)
        final_entry = Entry.objects.create(**self.entry_base)

        self.assertEqual(self.author.application_status, Author.PENDING)
        self.assertIsNotNone(self.author.application_date)

        final_entry.delete()  # delete 10th entry to retreat from novice list

        self.assertEqual(self.author.application_status, Author.ON_HOLD)
        self.assertIsNone(self.author.application_date)

    def test_message_preferences(self):
        some_author = Author.objects.create(username="author", email="3", is_novice=False)
        some_novice = Author.objects.create(username="novice", email="4")

        # ALL users (database default)
        msg_sent_by_novice = Message.objects.compose(some_novice, self.author, "test")
        msg_sent_by_author = Message.objects.compose(some_author, self.author, "test")
        self.assertNotEqual(msg_sent_by_author, False)
        self.assertNotEqual(msg_sent_by_novice, False)

        # Disabled
        self.author.message_preference = Author.DISABLED
        msg_sent_by_novice = Message.objects.compose(some_novice, self.author, "test")
        msg_sent_by_author = Message.objects.compose(some_author, self.author, "test")
        self.assertEqual(msg_sent_by_author, False)
        self.assertEqual(msg_sent_by_novice, False)

        # Authors (non-novices) only
        self.author.message_preference = Author.AUTHOR_ONLY
        msg_sent_by_novice = Message.objects.compose(some_novice, self.author, "test")
        msg_sent_by_author = Message.objects.compose(some_author, self.author, "test")
        self.assertNotEqual(msg_sent_by_author, False)
        self.assertEqual(msg_sent_by_novice, False)

        # Following only
        self.author.message_preference = Author.FOLLOWING_ONLY
        msg_sent_by_non_follower = Message.objects.compose(some_author, self.author, "test")
        self.assertEqual(msg_sent_by_non_follower, False)
        self.author.following.add(some_author)  # add following to send message
        msg_sent_by_follower = Message.objects.compose(some_author, self.author, "test")
        self.assertNotEqual(msg_sent_by_follower, False)

        # Blocking tests
        self.author.message_preference = Author.ALL_USERS
        self.author.blocked.add(some_author)
        can_recieve_msg_from_blocked_user = Message.objects.compose(some_author, self.author, "test")
        self.assertEqual(can_recieve_msg_from_blocked_user, False)
        can_send_msg_to_blocked_user = Message.objects.compose(self.author, some_author, "test")
        self.assertEqual(can_send_msg_to_blocked_user, False)

        # No self-messaging allowed
        can_send_message_to_self = Message.objects.compose(self.author, self.author, "test")
        self.assertEqual(can_send_message_to_self, False)

    def test_follow_all_categories_on_creation(self):
        category_1 = Category.objects.create(name="test")
        Category.objects.create(name="test2")
        some_user = Author.objects.create(username="some_user", email="5")
        self.assertIn(category_1, some_user.following_categories.all())
        self.assertEqual(some_user.following_categories.all().count(), 2)

    def test_absolute_url(self):
        absolute_url = reverse("user-profile", kwargs={"username": self.author.username})
        self.assertEqual(absolute_url, self.author.get_absolute_url())

    def test_entry_nice(self):
        # No entry = No nice entry
        self.assertEqual(None, self.author.entry_nice)

        # Entry with low vote rate
        entry = Entry.objects.create(**self.entry_base)
        self.assertEqual(None, self.author.entry_nice)

        # Entry with enough vote rate
        entry.vote_rate = Decimal("1.1")
        entry.save()
        self.assertEqual(entry, self.author.entry_nice)

        # Superior entry
        another_entry = Entry.objects.create(**self.entry_base, vote_rate=Decimal("3"))
        self.assertEqual(another_entry, self.author.entry_nice)


class CategoryModelTests(TransactionTestCase):
    @classmethod
    def setUp(cls):
        cls.category = Category.objects.create(name="şeker")

    def test_absolute_url(self):
        absolute_url = reverse("topic_list", kwargs={"slug": self.category.slug})
        self.assertEqual(absolute_url, self.category.get_absolute_url())

    def test_uniqueness(self):
        with self.assertRaises(IntegrityError):
            Category.objects.create(name="şeker")

        similar_category = Category.objects.create(name="seker")
        self.assertNotEqual(similar_category.slug, self.category.slug)

    def test_str(self):
        self.assertEqual(str(self.category), self.category.name)


class EntryModelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.author = Author.objects.create(username="user", email="0")
        cls.topic = Topic.objects.create_topic("test_topic")
        cls.entry_base = dict(topic=cls.topic, author=cls.author)
        cls.entry = Entry.objects.create(**cls.entry_base, content="CONtent İŞçI")

    def test_absolute_url(self):
        absolute_url = reverse("entry-permalink", kwargs={"entry_id": self.entry.pk})
        self.assertEqual(absolute_url, self.entry.get_absolute_url())

    def test_content_lower(self):
        self.assertEqual("content işçı", self.entry.content)

    def test_topic_ownership(self):
        self.assertEqual(self.author, self.topic.created_by)

        topic_with_no_ownership = Topic.objects.create_topic("test_topic2")
        self.assertIsNone(topic_with_no_ownership.created_by)

        new_entry = Entry.objects.create(author=self.author, topic=topic_with_no_ownership, is_draft=True)
        self.assertIsNone(topic_with_no_ownership.created_by)

        new_entry.is_draft = False
        new_entry.save()
        self.assertEqual(self.author, topic_with_no_ownership.created_by)

    def test_str(self):
        self.assertEqual(str(self.entry), f"{self.entry.id}#{self.entry.author}")

    def test_votes(self):
        # Initial vote should be 0
        self.assertEqual(self.entry.vote_rate.conjugate(), Decimal("0"))

        # Increase by .2
        self.entry.update_vote(Decimal(".2"))
        self.entry.refresh_from_db()
        self.assertEqual(self.entry.vote_rate, Decimal(".2"))

        # Increase by .2 again to ensure that it is incremental (not a replacement)
        self.entry.update_vote(Decimal(".2"))
        self.entry.refresh_from_db()
        self.assertEqual(self.entry.vote_rate, Decimal(".4"))

        # Increase by -.2 (decrease .2)
        self.entry.update_vote(Decimal("-.2"))
        self.entry.refresh_from_db()
        self.assertEqual(self.entry.vote_rate, Decimal(".2"))

        # Increase by change
        self.entry.update_vote(Decimal(".2"), change=True)
        self.entry.refresh_from_db()
        self.assertEqual(self.entry.vote_rate, Decimal(".6"))


class MementoModelTests(TransactionTestCase):
    @classmethod
    def setUp(cls):
        cls.author_1 = Author.objects.create(username="user1", email="1")
        cls.author_2 = Author.objects.create(username="user2", email="2")

    def test_unique_constraint(self):
        Memento.objects.create(holder=self.author_1, patient=self.author_2)

        # Make sure that the fields are evaluated differently
        Memento.objects.create(holder=self.author_2, patient=self.author_1)

        # Creating a non-unique object
        with self.assertRaises(IntegrityError):
            Memento.objects.create(holder=self.author_1, patient=self.author_2)

    def test_str(self):
        memento = Memento.objects.create(holder=self.author_1, patient=self.author_2)
        self.assertEqual(str(memento), f"Memento#1, from {self.author_1} about {self.author_2}")


class UserVerificationModelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.author = Author.objects.create(username="user", email="0")

    def test_no_multiple_verifications(self):
        UserVerification.objects.create(author=self.author, expiration_date=timezone.now())
        latest_uv = UserVerification.objects.create(author=self.author, expiration_date=timezone.now())
        list_uv_for_author = UserVerification.objects.filter(author=self.author)
        self.assertEqual(list_uv_for_author.count(), 1)
        self.assertEqual(latest_uv, list_uv_for_author.first())

    def test_email_confirmed_status(self):
        # For profile page email change status indicator
        # Create pending email confirmation
        uv_author = UserVerification.objects.create(author=self.author,
                                                    expiration_date=timezone.now() + datetime.timedelta(hours=12))
        self.assertEqual(self.author.email_confirmed, False)

        # No pending email confirmation
        uv_author.delete()
        self.assertEqual(self.author.email_confirmed, True)

        # There is a email confirmation sent, but it has been expired
        UserVerification.objects.create(author=self.author,
                                        expiration_date=timezone.now() - datetime.timedelta(hours=30))
        self.assertEqual(self.author.email_confirmed, True)


class EntryFavoritesModelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.author = Author.objects.create(username="user", email="0")
        cls.topic = Topic.objects.create_topic("test_topic")
        cls.entry = Entry.objects.create(topic=cls.topic, author=cls.author)

    def test_str(self):
        self.author.favorite_entries.add(self.entry)
        fav = EntryFavorites.objects.get(author=self.author, entry=self.entry)
        self.assertEqual(str(fav), "Entry favorisi #1")


class MessageModelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.author_1 = Author.objects.create(username="user1", email="1")
        cls.author_2 = Author.objects.create(username="user2", email="2")

    def test_read_at_time(self):
        some_message = Message.objects.compose(self.author_1, self.author_2, "body")
        self.assertIsNone(some_message.read_at)
        some_message.mark_read()
        self.assertIsNotNone(some_message.read_at)

    def test_str(self):
        some_message = Message.objects.compose(self.author_1, self.author_2, "body")
        self.assertEqual(str(some_message), "1")


class ConversationModelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.author_1 = Author.objects.create(username="user1", email="1")
        cls.author_2 = Author.objects.create(username="user2", email="2")

    def test_conversation_creation_on_messaging(self):
        # Check initial status
        conversation_count = Conversation.objects.all().count()
        self.assertEqual(conversation_count, 0)

        # A conversation started
        some_msg = Message.objects.compose(self.author_1, self.author_2, "gelmiyorsun artık günah çıkarmaya?")

        conversation_count = Conversation.objects.all().count()
        self.assertEqual(conversation_count, 1)

        # Get that conversation and check if the previous message is in it
        current_conversation = Conversation.objects.get(pk=1)
        self.assertIn(some_msg, current_conversation.messages.all())

        # Reply message, check also if that message in conversation and check no extra conversation is created
        # for it (it should append to newly created conversation)

        some_other_msg = Message.objects.compose(self.author_2, self.author_1, "işlemiyorum ki, evdeyim hep.")
        conversation_count = Conversation.objects.all().count()
        self.assertEqual(conversation_count, 1)
        self.assertIn(some_other_msg, current_conversation.messages.all())

        # Check participants
        self.assertIn(self.author_1, current_conversation.participants.all())
        self.assertIn(self.author_2, current_conversation.participants.all())

    def test_last_message(self):
        some_msg = Message.objects.compose(self.author_1, self.author_2, "baapoçun çen?!!")
        current_conversation = Conversation.objects.get(pk=1)
        self.assertEqual(some_msg, current_conversation.last_message)

        time.sleep(0.01)  # apparently auto_now_add fields will be exactly the same in the same block.
        some_other_msg = Message.objects.compose(self.author_1, self.author_2, "ya bi sktr git allah allah")
        self.assertEqual(some_other_msg, current_conversation.last_message)

    def test_str(self):
        Message.objects.compose(self.author_1, self.author_2, "baapoçun çen?!!")
        current_conversation = Conversation.objects.get(pk=1)
        self.assertEqual(str(current_conversation), "1<QuerySet ['user1', 'user2']>")


class GeneralReportModelTest(TestCase):
    def test_str(self):
        report = GeneralReport.objects.create(subject="subject")
        self.assertEqual(str(report), "subject <GeneralReport>#1")


class TopicModelTest(TransactionTestCase):
    @classmethod
    def setUp(cls):
        cls.some_topic = Topic.objects.create_topic("zeki müren")
        cls.author = Author.objects.create(username="user", email="0", is_novice=False)

    def test_uniqueness(self):
        with self.assertRaises(IntegrityError):
            Topic.objects.create_topic("zeki müren")

        similar_topic = Topic.objects.create_topic("zeki muren")
        self.assertNotEqual(similar_topic.slug, self.some_topic.slug)

    def test_existence(self):
        self.assertEqual(self.some_topic.exists, True)

    def test_has_entries(self):
        # Initial status
        self.assertEqual(self.some_topic.has_entries, False)

        # Add non-published entry
        Entry.objects.create(topic=self.some_topic, author=self.author, is_draft=True)
        self.assertEqual(self.some_topic.has_entries, False)

        # Add published entry
        Entry.objects.create(topic=self.some_topic, author=self.author)
        self.assertEqual(self.some_topic.has_entries, True)

    def test_latest_entry_date(self):
        # Initial status (no entry)
        self.assertEqual(self.some_topic.latest_entry_date(self.author), self.some_topic.date_created)

        # Self entry doesn't change output
        time.sleep(0.01)  # So that self.some_topic.date_created != some_entry.date_created
        some_entry = Entry.objects.create(topic=self.some_topic, author=self.author)
        self.assertEqual(self.some_topic.latest_entry_date(self.author), self.some_topic.date_created)

        # Some other person requests latest entry date
        some_other_author = Author.objects.create(username="user2", email="1", is_novice=False)
        self.assertEqual(self.some_topic.latest_entry_date(some_other_author), some_entry.date_created)

        # Block test
        some_other_author.blocked.add(self.author)
        self.assertEqual(self.some_topic.latest_entry_date(some_other_author), self.some_topic.date_created)

    def test_follow_check(self):
        # Initial status
        self.assertEqual(self.some_topic.follow_check(self.author), False)

        # Follow
        TopicFollowing.objects.create(topic=self.some_topic, author=self.author)
        self.assertEqual(self.some_topic.follow_check(self.author), True)

    def test_title_lower(self):
        weird_topic = Topic.objects.create_topic("wEİIrdo")
        self.assertEqual("weiırdo", weird_topic.title)

    def test_absolute_url(self):
        absolute_url = reverse("topic", kwargs={"slug": self.some_topic.slug})
        self.assertEqual(absolute_url, self.some_topic.get_absolute_url())

    def test_str(self):
        self.assertEqual(str(self.some_topic), "zeki müren")


class TopicFollowingModelTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.some_topic = Topic.objects.create_topic("hüseyin")
        cls.author = Author.objects.create(username="user", email="0", is_novice=False)

    def test_str(self):
        some_topic_following = TopicFollowing.objects.create(topic=self.some_topic, author=self.author)
        self.assertEqual(str(some_topic_following), "1 => user")