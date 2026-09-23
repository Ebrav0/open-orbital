import subprocess
import tempfile
import unittest
from pathlib import Path

from lab.coordinator.db import Database
from lab.observatory import server
from lab.safety import git_commit


class GitProvenanceTests(unittest.TestCase):
    def test_git_commit_works_from_linked_worktree(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            worktree = root / "worktree"

            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            subprocess.run(
                ["git", "-C", str(repo), "config", "user.name", "Lab Test"],
                check=True,
            )
            subprocess.run(
                ["git", "-C", str(repo), "config", "user.email", "lab@test.invalid"],
                check=True,
            )

            (repo / "file.txt").write_text("test\n")
            subprocess.run(["git", "-C", str(repo), "add", "file.txt"], check=True)
            subprocess.run(
                ["git", "-C", str(repo), "commit", "-q", "-m", "initial"],
                check=True,
            )

            expected = subprocess.run(
                ["git", "-C", str(repo), "rev-parse", "HEAD"],
                text=True,
                capture_output=True,
                check=True,
            ).stdout.strip()

            subprocess.run(
                [
                    "git",
                    "-C",
                    str(repo),
                    "worktree",
                    "add",
                    "-q",
                    "-b",
                    "linked-test",
                    str(worktree),
                ],
                check=True,
            )

            self.assertTrue((worktree / ".git").is_file())
            self.assertEqual(git_commit(worktree), expected)

    def test_create_job_persists_valid_git_commit(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "lab.sqlite")
            try:
                commit = "a" * 40
                spec = server().normalize(
                    {
                        "mode": "planets",
                        "duration": 1,
                        "seed": 1,
                        "jupiter_mass": 1,
                    }
                )

                job_id = db.create_job(
                    [spec],
                    "github",
                    {"git_commit": commit},
                    1.0,
                )

                self.assertEqual(db.job(job_id)["git_commit"], commit)
            finally:
                db.close()


if __name__ == "__main__":
    unittest.main()
