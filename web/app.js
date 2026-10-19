// SayHelp 前端逻辑：登录 + 会话历史 + 聊天（POST 型 SSE 逐字渲染）+ 卡片骨架。
// 纯 vanilla JS，无框架、无构建步骤。P4 将在 renderCard 中接入真实卡片数据。

const TOKEN_KEY = "sayhelp_token";

function getToken() {
  return localStorage.getItem(TOKEN_KEY);
}

function isLoggedIn() {
  return Boolean(getToken());
}

function authHeaders(extra) {
  const token = getToken();
  const headers = Object.assign({}, extra);
  if (token) headers["Authorization"] = "Bearer " + token;
  return headers;
}

// 统一 API 封装：自动附带 Bearer token，401 时跳回登录页。
async function api(path, options) {
  const opts = Object.assign({}, options);
  opts.headers = authHeaders(options && options.headers);
  const r = await fetch(path, opts);
  if (r.status === 401) {
    localStorage.removeItem(TOKEN_KEY);
    window.location.href = "/";
    throw new Error("登录已过期");
  }
  return r;
}

async function login(username, password) {
  const fd = new URLSearchParams({ username, password });
  const r = await fetch("/api/auth/login", {
    method: "POST",
    body: fd,
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
  });
  if (!r.ok) {
    let detail = "登录失败";
    try {
      const body = await r.json();
      if (body.detail) detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch (_) {
      /* 非 JSON 响应，保留默认提示 */
    }
    throw new Error(detail);
  }
  const data = await r.json();
  localStorage.setItem(TOKEN_KEY, data.access_token);
  return data.user;
}

// 解析累积的 SSE 文本，切出完整的 `event:/data:` 帧（以空行分隔）。
// 返回 { events: [{type, data}], rest }，rest 为尚未以空行结尾的不完整帧。
function parseSseChunk(buf) {
  const events = [];
  const frames = buf.split("\n\n");
  const rest = frames.pop(); // 最后一段可能不完整，留到下一轮
  for (const frame of frames) {
    let type = "message";
    const dataLines = [];
    for (const rawLine of frame.split("\n")) {
      const line = rawLine.trim();
      if (!line) continue;
      if (line.startsWith("event:")) {
        type = line.slice("event:".length).trim();
      } else if (line.startsWith("data:")) {
        dataLines.push(line.slice("data:".length).trim());
      }
    }
    if (dataLines.length === 0) continue;
    const raw = dataLines.join("\n");
    let data;
    try {
      data = JSON.parse(raw);
    } catch (_) {
      data = raw;
    }
    events.push({ type, data });
  }
  return { events, rest };
}

// 把 POST 型 SSE 的 response.body（ReadableStream）解析为事件序列。
// EventSource 仅支持 GET，POST 型 SSE 必须用 fetch + reader 手动解析。
async function* parseSse(stream) {
  const reader = stream.getReader();
  const dec = new TextDecoder();
  let buf = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    const { events, rest } = parseSseChunk(buf);
    buf = rest;
    for (const ev of events) yield ev;
  }
  buf += dec.decode(); // 冲刷最后未解码的字节
  if (buf) buf += "\n\n"; // 强制冲刷最后一个可能不完整的帧
  const { events } = parseSseChunk(buf);
  for (const ev of events) yield ev;
}

async function chatStream(conversationId, content, onEvent) {
  const r = await fetch("/api/chat/stream", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Authorization": "Bearer " + localStorage.getItem(TOKEN_KEY),
    },
    body: JSON.stringify({ conversation_id: conversationId, content }),
  });
  if (r.status === 401) {
    localStorage.removeItem(TOKEN_KEY);
    window.location.href = "/";
    throw new Error("登录已过期");
  }
  if (!r.ok) {
    let detail = "发送失败";
    try {
      const body = await r.json();
      if (body.detail) detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch (_) {
      /* 非 JSON 响应 */
    }
    throw new Error(detail);
  }
  for await (const ev of parseSse(r.body)) {
    onEvent(ev.type, ev.data);
  }
}

// 卡片骨架：P1 仅渲染占位结构，P4 接入真实数据。
// card.type === "order_select" → 订单选择卡片；"ticket_preview" → 建工单预览卡片。
function renderCard(card) {
  const el = document.createElement("div");
  el.className = "card";
  const type = card && card.type ? card.type : "unknown";
  el.dataset.type = type;
  if (type === "order_select") {
    el.classList.add("card-order-select");
    el.textContent = "[订单选择卡片占位] P4 接入真实数据";
  } else if (type === "ticket_preview") {
    el.classList.add("card-ticket-preview");
    el.textContent = "[建工单预览卡片占位] P4 接入真实数据";
  } else {
    el.textContent = "[未知卡片类型: " + type + "]";
  }
  return el;
}

/* ---------- 登录页 ---------- */

function initLoginPage() {
  const form = document.getElementById("login-form");
  if (!form) return;
  if (isLoggedIn()) {
    window.location.href = "/chat.html";
    return;
  }
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const username = document.getElementById("username").value.trim();
    const password = document.getElementById("password").value;
    const errorEl = document.getElementById("login-error");
    const submit = document.getElementById("login-submit");
    errorEl.hidden = true;
    submit.disabled = true;
    submit.textContent = "登录中…";
    try {
      await login(username, password);
      window.location.href = "/chat.html";
    } catch (err) {
      errorEl.textContent = err.message || "登录失败";
      errorEl.hidden = false;
      submit.disabled = false;
      submit.textContent = "登录";
    }
  });
}

/* ---------- 聊天页 ---------- */

const chatState = {
  currentConversationId: null,
  streaming: false,
};

function escapeHtml(s) {
  const div = document.createElement("div");
  div.textContent = s;
  return div.innerHTML;
}

function fmtDate(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function messagesEl() {
  return document.getElementById("messages");
}

function clearMessages() {
  const el = messagesEl();
  el.innerHTML = '<p class="empty-hint">选择或新建一个会话，开始提问。</p>';
}

function appendMessage(role, content) {
  const el = messagesEl();
  const hint = el.querySelector(".empty-hint");
  if (hint) hint.remove();

  const row = document.createElement("div");
  row.className = "message " + role;

  const bubble = document.createElement("div");
  bubble.className = "bubble";
  bubble.textContent = content;

  row.appendChild(bubble);
  el.appendChild(row);
  el.scrollTop = el.scrollHeight;
  return bubble;
}

// 把 SSE 事件落到界面上：status → 处理中提示；text → 增量追加 delta；done → 结束。
function handleStreamEvent(bubble, type, data) {
  if (type === "status") {
    bubble.textContent = "正在处理…";
    bubble.classList.add("pending");
  } else if (type === "text") {
    const delta = data && data.delta != null ? data.delta : "";
    if (bubble.classList.contains("pending")) {
      // 首个 delta 到达前清空「正在处理…」占位，确保最终正文为后端原文
      bubble.classList.remove("pending");
      bubble.textContent = "";
    }
    bubble.textContent += delta; // 逐 delta 增量渲染（后端按块下发，P1 为整段占位）
  }
  messagesEl().scrollTop = messagesEl().scrollHeight;
}

async function loadConversations() {
  const r = await api("/api/conversations");
  if (!r.ok) return;
  const list = await r.json();
  const ul = document.getElementById("conversation-list");
  ul.innerHTML = "";
  for (const conv of list) {
    const li = document.createElement("li");
    li.className = "conversation-item";
    li.dataset.id = conv.id;
    li.innerHTML =
      '<span class="conversation-title">会话 #' + escapeHtml(String(conv.id)) + "</span>" +
      '<span class="conversation-meta">' + escapeHtml(fmtDate(conv.updated_at)) + "</span>";
    li.addEventListener("click", () => selectConversation(conv.id));
    if (conv.id === chatState.currentConversationId) li.classList.add("active");
    ul.appendChild(li);
  }
}

async function loadMessages(conversationId) {
  const r = await api("/api/conversations/" + conversationId + "/messages");
  if (!r.ok) return;
  const msgs = await r.json();
  clearMessages();
  for (const m of msgs) {
    appendMessage(m.role, m.content);
  }
}

async function selectConversation(conversationId) {
  chatState.currentConversationId = conversationId;
  document.querySelectorAll(".conversation-item").forEach((li) => {
    li.classList.toggle("active", Number(li.dataset.id) === conversationId);
  });
  await loadMessages(conversationId);
}

async function newConversation() {
  if (chatState.streaming) return;
  const r = await api("/api/conversations", { method: "POST" });
  if (!r.ok) return;
  const conv = await r.json();
  await loadConversations();
  await selectConversation(conv.id);
}

async function sendMessage() {
  if (chatState.streaming) return;
  const input = document.getElementById("input");
  const content = input.value.trim();
  if (!content) return;
  if (chatState.currentConversationId == null) {
    const r = await api("/api/conversations", { method: "POST" });
    if (!r.ok) return;
    const conv = await r.json();
    await loadConversations();
    chatState.currentConversationId = conv.id;
    document.querySelectorAll(".conversation-item").forEach((li) => {
      li.classList.toggle("active", Number(li.dataset.id) === conv.id);
    });
    clearMessages();
  }

  input.value = "";
  const conversationId = chatState.currentConversationId;
  appendMessage("user", content);
  const bubble = appendMessage("assistant", "");

  chatState.streaming = true;
  document.getElementById("send").disabled = true;
  try {
    await chatStream(conversationId, content, (type, data) => {
      handleStreamEvent(bubble, type, data);
    });
    if (bubble.textContent === "正在处理…") bubble.textContent = "";
  } catch (err) {
    bubble.classList.add("error");
    bubble.textContent = "发送失败：" + (err.message || "未知错误");
  } finally {
    bubble.classList.remove("pending");
    chatState.streaming = false;
    document.getElementById("send").disabled = false;
    loadConversations(); // 刷新 updated_at 排序
  }
}

async function loadUser() {
  const r = await api("/api/auth/me");
  if (!r.ok) return;
  const u = await r.json();
  const el = document.getElementById("user-name");
  if (el) el.textContent = u.display_name || u.username;
}

function initChatPage() {
  const compose = document.getElementById("compose");
  if (!compose) return;
  if (!isLoggedIn()) {
    window.location.href = "/";
    return;
  }

  document.getElementById("logout").addEventListener("click", () => {
    localStorage.removeItem(TOKEN_KEY);
    window.location.href = "/";
  });

  document.getElementById("new-conversation").addEventListener("click", newConversation);

  compose.addEventListener("submit", (e) => {
    e.preventDefault();
    sendMessage();
  });

  const input = document.getElementById("input");
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  });

  loadUser();
  loadConversations();
}

/* ---------- 启动 ---------- */

initLoginPage();
initChatPage();
