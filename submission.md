# Codebase Map: Mixtape

This document maps out the architecture, main files, data flows, design patterns, and bug reproduction steps for the Mixtape application.

---

## File and Module Responsibilities

## AI Usage
Case 1: As demo in class, debugging was done by skimming through to understand what the code is doing. Instead, I first used AI to go through the main functions to understand what the program is doing and layout the main pieces I need to understand and how everything is mapped together. This gives me a better understanding than skimming through and assuming. That was then layout into this document on how the models, routing layer, service layers are related. With this, I used AI for codebase navigation so I can connect one piece to another.
Case 2: I asked AI to generate me the regression tests. There were already provided test cases for some of the bugs, I asked AI to generate cases that were not covered. 

I used AI to generate the terminal outputs of what I am expecting for each output. Tests cases not not always accurately reflect what is happening and step by step reproduction takes time so AI generate commands like this to get verified AI output.
`"from app import create_app, db; from models import User, Song; from services.notification_service import rate_song, get_notifications; app = create_app({'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:'}); ctx = app.app_context(); ctx.push(); db.create_all(); sharer=User(username='sharer', email='s@x.com'); rater=User(username='rater', email='r@x.com'); db.session.add_all([sharer, rater]); db.session.flush(); s=Song(title='Golden Hour', artist='Solange', shared_by=sharer.id); db.session.add(s); db.session.commit(); rate_song(rater.id, s.id, 5); print('Notifications:', [n['body'] for n in get_notifications(sharer.id)])"`

### Core Configuration and Models
*   **[app.py]**: The application factory. Configures Flask, initializes Flask-SQLAlchemy (`db`), registers the blueprints (`/songs`, `/playlists`, `/users`, `/feed`), and sets up the database context.
*   **[models.py]**: Defines the SQLAlchemy data schemas and relationships.
    *   *Primary Models*: `User` (tracks streaks and credentials), `Song` (tracks shared music), `Playlist` (tracks curated lists), `Tag` (tracks genre/vibe tags), `Rating` (stores 1-5 song reviews), and `Notification` (tracks in-app alerts).
    *   *Join Tables*:
        *   `friendships`: A symmetric many-to-many join table connecting users.
        *   `song_tags`: A many-to-many join table mapping tags to songs.
        *   `playlist_entries`: A specialized many-to-many join table mapping songs to playlists. It holds metadata including `position` (for playlist sorting order), `added_by`, and `added_at`.

---

### Routing Layer (routes/)
All route modules parse incoming HTTP requests (JSON bodies, query parameters), handle error parsing, and return JSON payloads.
*   **[routes/songs.py](songs.py)**: Entry points for searching songs, fetching song details, rating songs, and recording listening events.
*   **[routes/playlists.py](playlists.py)**: Entry points for creating playlists, fetching playlist contents, and adding songs.
*   **[routes/users.py](users.py)**: Entry points for looking up user profiles, viewing active streaks, and managing notification lists.
*   **[routes/feed.py](feed.py)**: Entry points for fetching "listening now" activity and historic activity from friends.

---

### Service Layer (services/)
This layer encapsulates the core business logic and performs all database mutations.
*   **[services/search_service.py](search_service.py)**: Implements case-insensitive song querying by title and artist.
*   **[services/playlist_service.py](playlist_service.py)**: Handles playlist creation and retrieves playlist tracks sorted by their entry position.
*   **[services/streak_service.py](streak_service.py)**: Handles user listening history and calculates daily streaks based on consecutive listen days.
*   **[services/feed_service.py](feed_service.py)**: Compiles timelines of what friends are listening to (including a 24-hour active feed).
*   **[services/notification_service.py](notification_service.py)**: Orchestrates ratings and playlist additions, and generates `Notification` entries for affected users.

---

## Core Data Flow: Adding a Song to a Playlist

This traces what happens when a user adds a song to a collaborative playlist:

```
[ POST /playlists/<playlist_id>/songs ]
                  |
                  v
   [ routes/playlists.py: add_song() ]
                  | (Extracts body params: song_id, added_by)
                  v
[ services/notification_service.py: add_to_playlist() ]
                  |
                  +--> Checks database for Song, User, and Playlist models
                  +--> Appends Song to playlist.songs if not already present
                  |
                  v (If adder is NOT the original song sharer)
[ services/notification_service.py: create_notification() ]
                  |
                  v
         [ db.session.commit() ]
                  | (Saves entries to playlist_entries and notification tables)
                  v
       [ Return 201 Created JSON ]
```

1. **Client Action:** The client makes a `POST` request to `/playlists/<playlist_id>/songs` with JSON containing `{"song_id": "<UUID>", "added_by": "<UUID>"}`.
2. **Routing:** `add_song()` in `routes/playlists.py` receives the request, extracts the path parameter and body variables, and calls `add_to_playlist(playlist_id, song_id, added_by)`.
3. **Business Logic and Association:** In `services/notification_service.py`, `add_to_playlist()` verifies that all entities exist. It appends the song to the playlist's relationship, which automatically creates a join record in `playlist_entries`.
4. **Notification Trigger:** The function compares the song's original owner (`song.shared_by`) with the user who added it. If they are different, it calls `create_notification` to write a new alert row into the `notification` table.
5. **Database Commit:** The transaction is committed to save both the playlist entry and the notification, returning a `201` success status to the client.

---

## Architectural Patterns Noticed

1. **Thin Routing Layer (Controller-Service Separation)**:
   Blueprints under `routes/` do not query or mutate the database directly. Instead, they act as thin controllers that parse input data (like JSON or query params), call service routines, catch `ValueError` exceptions to translate them into standard HTTP status codes (`400` for bad input, `404` for missing records), and return responses via `jsonify`.
   
2. **UUID Primary Keys**:
   Instead of traditional auto-incrementing integers, all records use standard v4 UUID string identifiers. This decouples database generation from sequence collision, though it requires strict string validation in the routes.
   
3. **Database-Driven Relationships**:
   Many-to-many associations (like friendships, song tags, and playlists) are handled through explicit database association tables rather than simple arrays. Rich join tables like `playlist_entries` append metadata directly to connection instances, allowing the app to scale relational constraints safely.

---

## Root Cause Analysis

### Issue 1: My listening streak keeps resetting
*   **How was reproduced:**
    *   *Inputs:* A user with `listening_streak = 5` and a `last_listened_at` timestamp set to a Saturday (e.g., June 27, 2026).
    *   *Sequence of actions:* Recorded a listening event for that user on Sunday (e.g., June 28, 2026).
    *   *Data condition:* The consecutive-day gap `days_since_last` is exactly 1 day.
    *   *Trigger:* The logic triggered an execution path that reset the user's streak to 1 instead of incrementing it to 6. This was also verified by the failure of the unit test `test_streak_increments_on_sunday`.
*   **Found the root cause:** Traced the `/songs/<song_id>/listen` POST route in `routes/songs.py` which calls `record_listening_event` in `services/streak_service.py`. Followed the call stack into `update_listening_streak()`. Inspected line 73 and noticed the condition `and today.weekday() != 6` on the increment block, which specifically targets Sundays and changes the execution flow.
*   **The root cause:** Python's `datetime.date.weekday()` returns `6` for Sunday. In `streak_service.py`, the condition `elif days_since_last == 1 and today.weekday() != 6:` explicitly prevented the streak from incrementing if the current day was Sunday. When a user listened on Sunday after listening on Saturday, `days_since_last == 1` was true, but `today.weekday() != 6` was false. This caused the streak logic to bypass the increment block and fall into the `else` block, resetting `user.listening_streak = 1`.
*   **Fix and side-effect check:** Removed `and today.weekday() != 6` from the conditional check. This allows any consecutive-day listening event (including Saturday-to-Sunday) to increment the streak. Verified that non-consecutive days (skipped days) still correctly reset the streak to 1, and same-day listens (double counting) do not change the streak. The unit tests in `tests/test_streaks.py` (specifically `test_streak_increments_on_sunday`) now pass.

### Issue 2: Friends Listening Now shows people from yesterday
*   **How was reproduced:**
    *   *Inputs:* A user and an active friend. The friend has a listening event recorded 10 hours ago (representing the previous calendar day).
    *   *Sequence of actions:* Queried the user's friend feed via `GET /feed/<user_id>/listening-now`.
    *   *Data condition:* The friend's activity timestamp is older than the local calendar day's start but less than 24 hours ago.
    *   *Trigger:* The endpoint returned the friend's 10-hour-old listen event in the "Listening Now" section, showing outdated listening history from yesterday.
*   **Found the root cause:** Followed the routing endpoint `/feed/<user_id>/listening-now` in `routes/feed.py` to `get_friends_listening_now` in `services/feed_service.py`. Checked `RECENT_THRESHOLD` on line 13 and confirmed it was set to 24 hours.
*   **The root cause:** The `RECENT_THRESHOLD` constant in `feed_service.py` was set to `timedelta(hours=24)`. In a real-time listening feed, "now" is expected to span a short period (e.g., 30 minutes to match the seed data comment), whereas 24 hours includes activities from the previous calendar day. Because of this, the database filter `ListeningEvent.listened_at >= cutoff` queried and returned events that were up to a day old.
*   **Fix and side-effect check:** Changed `RECENT_THRESHOLD` to `timedelta(minutes=30)`. Verified that friends who listened 10 hours ago are successfully filtered out of the "Listening Now" feed, while friends who listened 10-20 minutes ago are still included. Confirmed that the separate historic `get_activity_feed` remains unaffected because it does not use the `RECENT_THRESHOLD` constant and instead relies on a numeric query limit.

### Issue 3: The same song keeps showing up twice in search
*   **How was reproduced:**
    *   *Inputs:* Search query "Crown Heights".
    *   *Sequence of actions:* Called the search endpoint `/songs/search?q=Crown`.
    *   *Data condition:* The target song *Crown Heights Anthem* was seeded with 3 distinct tags.
    *   *Trigger:* The search response returned the same song 3 times in the results list.
*   **Found the root cause:** Followed `/songs/search` in `routes/songs.py` to `search_songs()` in `services/search_service.py`. Inspected the database query.
*   **The root cause:** The query in `search_songs` used `.outerjoin(song_tags, Song.id == song_tags.c.song_id)` to join the song tags association table. Since the query only filters on `Song.title` and `Song.artist` and does not project or group by tags, the join is redundant. However, because a song has multiple tags, the database join generated $N$ rows for a song with $N$ tags. Because the query did not use `.distinct()`, the database returned duplicate rows, resulting in duplicate model objects.
*   **Fix and side-effect check:** Removed the redundant `.outerjoin(song_tags)` from the query. Verified that searching for *Crown Heights Anthem* now returns exactly one copy. Checked that the tags are still loaded and returned in the serialized dictionary via the subquery-loaded relationship defined on the `Song` model, confirming no loss of detail.

### Issue 4: I got notified when a friend added my song to a playlist but not when they rated it
*   **How was reproduced:**
    *   *Inputs:* User A has shared a song. User B rates User A's song with a score of 5.
    *   *Sequence of actions:* Made a `POST` request to `/songs/<song_id>/rate` representing User B rating the song.
    *   *Data condition:* User B is not the original sharer of the song.
    *   *Trigger:* The rating was successfully stored in the database, but querying User A's notifications via `/users/<user_id>/notifications` returned an empty list.
*   **Found the root cause:** Traced `/songs/<song_id>/rate` in `routes/songs.py` to `rate_song` in `services/notification_service.py`. Compared the function structure with `add_to_playlist` in the same service.
*   **The root cause:** The function `rate_song` recorded the rating in the database but lacked any notification dispatch logic. It did not perform a check to see if the rater was different from the original song sharer (`song.shared_by != user_id`) and failed to call `create_notification()` to write a notification entry.
*   **Fix and side-effect check:** Added a conditional notification block to `rate_song` before committing the transaction. If the rating user is not the song's original sharer, it calls `create_notification` with type `song_rated` and a description of the rating. Created a new unit test suite (`tests/test_notifications.py`) to verify notification creation when rated by others, and the absence of notifications when rating one's own song. All tests pass.

### Issue 5: The last song in a playlist never shows up
*   **How was reproduced:**
    *   *Inputs:* A playlist containing 5 songs.
    *   *Sequence of actions:* Fetched the playlist songs via `/playlists/<playlist_id>/songs`.
    *   *Data condition:* The playlist has multiple songs ordered by their entry position.
    *   *Trigger:* The endpoint returned only the first 4 songs, leaving the 5th song missing.
*   **Found the root cause:** Traced the playlist songs route in `routes/playlists.py` to `get_playlist_songs` in `services/playlist_service.py`. Inspected the return statement on line 66.
*   **The root cause:** The return statement in `get_playlist_songs` was written as `return [song.to_dict() for song in songs[:-1]]`. The Python list slice `[:-1]` truncates the list by dropping the final element. This off-by-one error prevented the last song of any playlist from being returned.
*   **Fix and side-effect check:** Changed the return statement to `[song.to_dict() for song in songs]` to return all songs in the list. Verified that a 5-song playlist now returns all 5 songs in the correct ascending order of their position, and empty playlists still return an empty list without errors. Unit tests in `tests/test_playlists.py` now pass.

## Regression Tests
A test was added to verify the rating notifications:
*   **File:** [test_notifications.py]
*   **What it verifies:** It asserts that when User B rates User A's song, a `song_rated` notification is generated for User A, and that when User A rates their own song, no notification is created.
*   **Why it would have failed against the buggy code:** Prior to the fix, `rate_song()` had no code invoking `create_notification()`. Therefore, `get_notifications(sharer.id)` would have returned an empty list, failing the assertion `assert len(sharer_notifs) == 1`.
Additionally, existing test files covered the Sunday streak and playlist slicing issues:
*   `test_streak_increments_on_sunday` in `tests/test_streaks.py`: Asserted Sunday streaks incremented to 2. It failed before the fix with `AssertionError: assert 1 == 2`.
*   `test_playlist_returns_all_songs` in `tests/test_playlists.py`: Asserted that a playlist returns all 5 songs. It failed before the fix with `AssertionError: assert 4 == 5` due to the slicing off-by-one error.