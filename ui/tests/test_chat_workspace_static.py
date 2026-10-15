"""Static contract checks for the additive Chat workspace."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class ChatWorkspaceContract(unittest.TestCase):
    def test_chat_workspace_is_separate_from_runner_ui(self):
        main = (ROOT / "ui/static/index.html").read_text(encoding="utf-8")
        chats = (ROOT / "ui/static/chats.html").read_text(encoding="utf-8")
        module = (ROOT / "ui/static/js/chats-workspace.js").read_text(encoding="utf-8")
        self.assertIn('href="/chats.html"', main)
        self.assertIn('id="chatView"', main)
        self.assertIn('id="chatList"', chats)
        self.assertIn('id="chatComposer"', chats)
        self.assertIn('/api/chats/messages/add', module)
        self.assertIn('/api/chats/create', module)
        self.assertIn('textContent = message.text', module)
        self.assertNotIn('innerHTML = message.text', module)
        self.assertIn('AI replies are not available yet', module)


if __name__ == "__main__":
    unittest.main()
