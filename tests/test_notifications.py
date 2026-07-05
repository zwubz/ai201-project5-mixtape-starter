"""
tests/test_notifications.py — Mixtape

Tests for rating notifications.
"""

import pytest
from app import create_app, db
from models import User, Song, Notification, Rating
from services.notification_service import rate_song, get_notifications


@pytest.fixture
def app():
    app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:"})
    with app.app_context():
        db.create_all()
        yield app
        db.drop_all()


def test_rating_creates_notification(app):
    """Rating a song should notify the original sharer if the rater is a different user."""
    with app.app_context():
        sharer = User(username="sharer", email="sharer@example.com")
        rater = User(username="rater", email="rater@example.com")
        db.session.add_all([sharer, rater])
        db.session.flush()

        song = Song(title="Target Track", artist="Sharer's Band", shared_by=sharer.id)
        db.session.add(song)
        db.session.commit()

        # Rate the song
        rate_song(user_id=rater.id, song_id=song.id, score=5)

        # Rater should have no notification
        rater_notifs = get_notifications(rater.id)
        assert len(rater_notifs) == 0

        # Sharer should have a notification
        sharer_notifs = get_notifications(sharer.id)
        assert len(sharer_notifs) == 1
        assert sharer_notifs[0]["type"] == "song_rated"
        assert "rater rated your song 'Target Track' 5 stars" in sharer_notifs[0]["body"]


def test_rating_does_not_create_notification_for_self(app):
    """Rating one's own song should not trigger a notification."""
    with app.app_context():
        sharer = User(username="sharer", email="sharer@example.com")
        db.session.add(sharer)
        db.session.flush()

        song = Song(title="Target Track", artist="Sharer's Band", shared_by=sharer.id)
        db.session.add(song)
        db.session.commit()

        # Sharer rates own song
        rate_song(user_id=sharer.id, song_id=song.id, score=5)

        sharer_notifs = get_notifications(sharer.id)
        assert len(sharer_notifs) == 0
