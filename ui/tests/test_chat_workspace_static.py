"""Static contracts for future capabilities integrated into the original UI."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class IntegratedWorkspaceContract(unittest.TestCase):
    def test_original_workspace_remains_primary_product_shell(self):
        main = (ROOT / "ui/static/index.html").read_text(encoding="utf-8")
        app = (ROOT / "ui/static/app.js").read_text(encoding="utf-8")
        css = (ROOT / "ui/static/css/future-integrated.css").read_text(encoding="utf-8")
        ui_main = (ROOT / "ui/main.py").read_text(encoding="utf-8")

        # Original ownership/navigation remains primary.
        for token in ('id="chatNav"', 'id="workflowNav"', 'id="promptNav"', 'id="chatView"', 'id="workflowView"'):
            self.assertIn(token, main)
        self.assertNotIn('href="/chats.html"', main)
        self.assertNotIn('href="/library.html"', main)
        self.assertNotIn('href="/settings.html"', main)
        self.assertIn('url = f"http://{args.host}:{server.port}/"', ui_main)
        self.assertNotIn('/chats.html"', ui_main)

        # Future capability is additive inside the original Project header/composer.
        for token in (
            'id="conversationTools"',
            'id="conversationSelect"',
            'id="newConversationButton"',
            'id="composerMode"',
            'id="taskModeButton"',
            'id="chatModeButton"',
            'id="taskListButton"',
            'id="taskHistoryButton"',
            'id="workspaceOptionField"',
            'id="taskListBackdrop"',
            'id="taskHistoryBackdrop"',
        ):
            self.assertIn(token, main)

        self.assertIn('/api/chats/turn', app)
        self.assertIn('/api/tasks/create', app)
        self.assertIn('/api/tasks/list/parse', app)
        self.assertIn('/api/tasks/list/export', app)
        self.assertIn('/api/tasks?root=', app)
        self.assertIn('selectedIsolatedWorkspaceAvailable', app)
        self.assertIn('Run as Task', app)
        self.assertIn('Task List', app)

        # Chat mode hides Task-only clutter instead of introducing another shell.
        self.assertIn('body[data-composer-mode="chat"] #workflowPicker', css)
        self.assertIn('body[data-composer-mode="chat"] #optionsButton', css)
        self.assertIn('.composer-mode-toggle', css)
        self.assertIn('.conversation-tools', css)

    def test_standalone_future_pages_are_compatibility_surfaces_only(self):
        chats = (ROOT / "ui/static/chats.html").read_text(encoding="utf-8")
        chat_module = (ROOT / "ui/static/js/chats-workspace.js").read_text(encoding="utf-8")
        library = (ROOT / "ui/static/library.html").read_text(encoding="utf-8")
        settings = (ROOT / "ui/static/settings.html").read_text(encoding="utf-8")

        self.assertIn('id="chatList"', chats)
        self.assertIn('/api/chats/turn', chat_module)
        self.assertIn('id="libraryScope"', library)
        self.assertIn('id="interface"', settings)
        # Compatibility pages must not become the primary entry/navigation again.
        main = (ROOT / "ui/static/index.html").read_text(encoding="utf-8")
        self.assertNotIn('Open Chats workspace', main)
        self.assertNotIn('Open Library', main)
        self.assertNotIn('Open Settings', main)


if __name__ == "__main__":
    unittest.main()
