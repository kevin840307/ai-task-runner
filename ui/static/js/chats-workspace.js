const element = (id) => document.getElementById(id);
let currentChat = null;
let chats = [];
let projects = [];

async function request(url, payload) {
  const options = payload === undefined ? {} : {
    method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(payload)
  };
  const response = await fetch(url, options);
  const data = await response.json();
  if (!response.ok || data.error) throw new Error(data.error || "Request failed");
  return data;
}
function report(error) { element("chatError").textContent = error?.message || String(error); }
function clearError() { element("chatError").textContent = ""; }
function selectChat(id) {
  currentChat = chats.find(chat => chat.chat_id === id) || null;
  element("chatTitle").textContent = currentChat?.title || "Select or create a Chat";
  element("chatPath").textContent = currentChat?.root_path || "";
  const writable = Boolean(currentChat?.path_available);
  element("chatText").disabled = !writable;
  element("chatSend").disabled = !writable;
  element("chatNotice").textContent = currentChat && !writable
    ? "Path unavailable · History is read-only."
    : "Messages are stored as conversation notes. AI replies are not available yet. Use Tasks to run AI workflows.";
  for (const button of element("chatList").querySelectorAll("button[data-id]")) {
    button.dataset.active = String(button.dataset.id === id);
  }
  loadMessages();
}
async function loadMessages() {
  const container = element("chatMessages");
  container.replaceChildren();
  if (!currentChat) return;
  const id = currentChat.chat_id;
  try {
    const result = await request("/api/chats/messages?chat_id=" + encodeURIComponent(id));
    if (id !== currentChat?.chat_id) return;
    for (const message of result.messages) {
      const bubble = document.createElement("div");
      bubble.className = "chat-bubble";
      bubble.textContent = message.text;
      container.append(bubble);
    }
    container.scrollTop = container.scrollHeight;
  } catch (error) { report(error); }
}
async function loadChats(keepSelection = true) {
  clearError();
  const data = await request("/api/chats");
  chats = data.chats;
  const selectedProject = element("chatProject").value;
  const list = element("chatList");
  list.replaceChildren();
  for (const chat of chats.filter(item => !selectedProject || item.root_path === selectedProject)) {
    const button = document.createElement("button");
    button.type = "button";
    button.dataset.id = chat.chat_id;
    button.textContent = chat.title + (chat.path_available ? "" : " · Path unavailable");
    button.addEventListener("click", () => selectChat(chat.chat_id));
    list.append(button);
  }
  const selectedId = keepSelection ? currentChat?.chat_id : null;
  selectChat(selectedId && [...list.children].some(button => button.dataset.id === selectedId) ? selectedId : "");
}
async function loadProjects() {
  const data = await request("/api/projects");
  projects = data.projects || [];
  const selector = element("chatProject");
  for (const project of projects) {
    const option = document.createElement("option");
    option.value = project.path;
    option.textContent = project.name + (project.exists ? "" : " · Path unavailable");
    option.disabled = !project.exists;
    selector.append(option);
  }
}
element("chatProject").addEventListener("change", () => { loadChats(false).catch(report); });
element("newChat").addEventListener("click", async () => {
  const root = element("chatProject").value;
  if (!root) { report(new Error("Select a project first.")); return; }
  try {
    const created = await request("/api/chats/create", {root});
    await loadChats(false);
    selectChat(created.chat_id);
  } catch (error) { report(error); }
});
element("chatComposer").addEventListener("submit", async event => {
  event.preventDefault();
  if (!currentChat) return;
  const id = currentChat.chat_id;
  const text = element("chatText").value.trim();
  if (!text) return;
  element("chatSend").disabled = true;
  try {
    await request("/api/chats/messages/add", {chat_id: id, text});
    element("chatText").value = "";
    await loadMessages();
  } catch (error) { report(error); }
  finally { element("chatSend").disabled = !currentChat?.path_available; }
});
Promise.all([loadProjects(), loadChats()]).catch(report);
