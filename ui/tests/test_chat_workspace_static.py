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
        settings = (ROOT / "ui/static/settings.html").read_text(encoding="utf-8")
        ui_main = (ROOT / "ui/main.py").read_text(encoding="utf-8")

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

        self.assertIn('aria-label="Global navigation"', chats)
        self.assertIn('aria-label="Chats context"', chats)
        self.assertIn('aria-label="Global navigation"', library)
        self.assertIn('aria-label="Library context"', library)
        self.assertIn('aria-label="Global navigation"', settings)
        self.assertIn('aria-label="Settings context"', settings)
        self.assertIn('/chats.html"', ui_main)
        self.assertIn('/api/tasks?attention=1&limit=10', chat_module)
        self.assertIn('Load older Tasks', chat_module)
        self.assertIn('available_actions', chat_module)
        self.assertIn('runtime.updated_at || task.updated_at', chat_module)
        self.assertIn('task.latest_execution_started_at || latest.started_at', chat_module)
        self.assertNotIn('Math.min(500, taskVisibleLimit + 100)', chat_module)
        self.assertIn('addDetailLine(root, "Instruction", task.instruction)', chat_module)
        self.assertIn('addDetailLine(root, "Backend"', chat_module)
        self.assertIn('addDetailLine(root, "Model"', chat_module)
        self.assertGreater(chats.index('id="taskTitle"'), chats.index('id="taskAdvanced"'))
        self.assertNotIn('</script>\\n<script', library)
        self.assertNotIn('</script>\\n<script', settings)
        self.assertIn('library.clear_search', library_module)
        self.assertIn('!currentChat.path_available', chat_module)
        self.assertIn('currentChat.archived', chat_module)
        self.assertLess(chat_module.index('!currentChat.path_available'), chat_module.index('currentChat.archived'))
        for page in (chats, library, settings):
            self.assertIn('body{display:block;width:100%;height:100vh;overflow:hidden}', page)

        self.assertIn('id="libraryScope"', library)
        self.assertIn('id="workflowLibraryTab"', library)
        self.assertIn('id="promptLibraryTab"', library)
        self.assertIn('/workflow-studio-app/index.html', library_module)
        self.assertIn('source:"prompt"', library_module)
        self.assertNotIn('DEFAULT_WORKFLOW_NAME = "ralphy_ai_validate.yaml"', (ROOT / "ui/static/app.js").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
