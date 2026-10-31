from app.core.settings import Settings
from app.db.learning import SqlLearningRepository
from app.db.session import Database
from app.services.catalog import seed_first_lesson


def main() -> None:
    database = Database(Settings())
    try:
        lesson = seed_first_lesson(SqlLearningRepository(database))
        print(f"Published {lesson.lesson_id} {lesson.version} ({lesson.content_hash}).")
    finally:
        database.dispose()


if __name__ == "__main__":
    main()
