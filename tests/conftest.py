import os

# Set a safe database before pytest imports any application module. Individual
# integration tests may replace this with their own temporary file, but no test
# collection order may ever fall through to the developer's real local database.
os.environ["STORAGE_BACKEND"] = "sqlite"
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
