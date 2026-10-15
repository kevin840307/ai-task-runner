"""Static contract checks for the future Chat/Task/Library product shell."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class ChatWorkspaceContract(unittest.TestCase):
    def test_new_shell_is_additive_and_reuses_existing_runtime_and_editors(self):
        main = (ROOT / "ui/static/index.html").read_text(encoding="utf-8")
        chats = (ROOT / "ui/static/chats.html").read_text(encoding="utf-8")
        chat_module = (ROOT / "ui/static/js/chats-workspace.js").read_text(encoding="utf-8")
        library = (ROOT / "ui/static/library.html").read_text(encoding="utf-8")
        library_module = (ROOT / "ui/static/js/library.js").read_text(encoding="utf-8")

        self.assertIn('href="/chats.html"', main)
        self.assertIn('href="/library.html"', main)
        self.assertIn('id="chatView"', main)  # legacy/runtime view remains available
        self.assertIn('id="chatList"', chats)
        self.assertIn('id="chatComposer"', chats)
        self.assertIn('id="tasksPanel"', chats)
        self.assertIn('id="taskListEditor"', chats)
        self.assertIn('id="taskListYamlPanel"', chats)
        self.assertIn('/api/chats/turn', chat_module)
        self.assertIn('/api/tasks/create', chat_module)
        self.assertIn('/api/tasks/list/parse', chat_module)
        self.assertIn('/api/tasks/list/export', chat_module)
        self.assertIn('textContent = message.text', chat_module)
        self.assertNotIn('innerHTML = message.text', chat_module)

        self.assertIn('id="libraryScope"', library)
        self.assertIn('id="workflowLibraryTab"', library)
        self.assertIn('id="promptLibraryTab"', library)
        self.assertIn('/workflow-studio-app/index.html', library_module)
        self.assertIn('source:"prompt"', library_module)


if __name__ == "__main__":
    unittest.main()
