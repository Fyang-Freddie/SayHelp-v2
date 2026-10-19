# SayHelp P1 — 认证授权、会话消息、SSE 底座、前端骨架 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task (user-selected execution method). Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 P0 的模型/迁移底座上，交付可运行的认证授权、会话与消息 API、SSE 流式底座和原生前端骨架，为 P3 的 Agent 主链路提供「登录态注入 + 会话 + 流式传输」这三块基础设施。

**Architecture:** FastAPI 应用 + JWT 认证（`pyjwt` + bcrypt 复用 seed 的密码哈希）+ SQLAlchemy 会话/消息读写 + `StreamingResponse` 的 SSE 事件流（`text/event-stream`）+ 原生 HTML/CSS/JS 前端（`fetch`+`ReadableStream` 解析 POST 型 SSE）。SSE 事件契约（text/status/reference/card/error/done）在 P1 即定型，P3 只替换「生成回答」的占位逻辑。

**Tech Stack:** Python 3.13.9、FastAPI、uvicorn、pyjwt、bcrypt、SQLAlchemy 2.0、pydantic v2、原生前端（无框架）。

**Spec:** `docs/superpowers/specs/2026-10-19-sayhelp-architecture.md`（§3.1 用户表、§3.3 会话/消息表、§4.5 隐藏身份注入、§4.6 API/SSE 契约）。P1 只实现认证/会话/SSE 底座；`resume`（interrupt 恢复）与交互卡片生成属 P4，P1 仅预置 `card` 事件类型与前端卡片渲染骨架，不产生真实 interrupt。

## Global Constraints

- 语言：与用户中文沟通；代码/注释中文与英文混用，关键注释中文。
- Python 3.13.9（Anaconda `D:\anaconda\anaconda_files\python.exe`）；MySQL 8（Docker，端口 3307）；单元测试用 `sqlite:///:memory:`。
- 红线（不可违反）：不伪造业务数据、不冒充真人坐席、不谎称接通/已提交；jev 不得擅自改为主力模型；`.env` 只提交 `.env.example` 占位、不提交真实密钥；不伪造文献/接口（Context7 不可用则用 WebFetch 并标注来源）。
- 已锁定决策（D1–D8）：本地账户+JWT（D1）；转人工=内置真实人工工作台（D2）；仅 `create_ticket` 为真实写工具（D3）；主力/改写/摘要/裁判统一 `deepseek-flash`、jev 独立（D4）；BGE-M3/reranker 本地自托管（D5）；训练切分保留 78.8/10.8/10.4%（D6）；「其他」单独成类（D7）；Milvus/Langfuse Docker 自托管（D8）。
- `alembic.ini` 须 ASCII-only（alembic 用 GBK 读它）；索引名须库内全局唯一（SQLite 测试）；自增 PK 用 `BigIntPK`。

## Review Focus

1. **越权读会话/消息**：用户 A 请求用户 B 的 `GET /api/conversations/{id}/messages` 必须 404（不泄露存在性），列表接口只返回本人会话。
2. **伪造/过期 JWT**：篡改签名、过期、`sub` 指向不存在用户 → 401。
3. **停用账号**：`is_active=false` 用户登录或携带其 token 访问 → 401/403，不通过。
4. **SSE 对不存在/非本人的会话流式**：`POST /api/chat/stream` 传他人 `conversation_id` → 立即 404 且不产生任何消息；传本人不存在的会话 → 404。
5. **反馈幂等**：对同一消息连续两次 👍 → 只保留一次（`feedback.type` 单值覆盖），不产生重复行。

以上 5 类分别由 Task 3/2/2/4/4 的测试钉住。

---

### Task 1: 安全依赖与基元（JWT + 密码哈希 + Settings 扩展）

**Files:**
- Modify: `requirements.txt`
- Modify: `app/config.py:3-29`
- Create: `app/auth/__init__.py`
- Create: `app/auth/security.py`
- Test: `tests/test_security.py`

**Interfaces:**
- Consumes: `app.config.Settings`（P0）。
- Produces:
  - `app.auth.security.hash_password(plain: str) -> str`
  - `app.auth.security.verify_password(plain: str, hashed: str) -> bool`
  - `app.auth.security.create_access_token(user_id: int, role: str) -> str`
  - `app.auth.security.decode_access_token(token: str) -> dict`（含 `sub`、`role`，失败抛 `JWTError`）
  - `Settings.jwt_secret: str`、`Settings.jwt_algorithm: str`、`Settings.access_token_expire_minutes: int`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_security.py
import pytest
import jwt
from app.auth.security import (
    create_access_token, decode_access_token, hash_password, verify_password,
)


def test_password_hash_roundtrip():
    hashed = hash_password("SayHelp123!")
    assert hashed != "SayHelp123!"
    assert verify_password("SayHelp123!", hashed)
    assert not verify_password("wrong", hashed)


def test_password_hash_is_bcrypt():
    assert hash_password("x").startswith("$2")


def test_token_roundtrip_carries_sub_and_role():
    token = create_access_token(user_id=7, role="customer")
    payload = decode_access_token(token)
    assert payload["sub"] == "7"
    assert payload["role"] == "customer"


def test_token_rejects_tampering():
    token = create_access_token(user_id=7, role="customer")
    with pytest.raises(jwt.InvalidTokenError):
        decode_access_token(token + "x")
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_security.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'app.auth'` 或 `jwt` 未安装）

- [ ] **Step 3: 加依赖 + Settings 字段**

`requirements.txt` 追加：
```
fastapi>=0.115,<1.0
uvicorn[standard]>=0.30,<1.0
pyjwt>=2.9,<3.0
python-multipart>=0.0.9,<1.0
```
`app/config.py` 的 `Settings` 内追加：
```python
    jwt_secret: str = "dev-secret-change-me"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24
```
`.env.example` 追加（占位，不提交真实密钥）：
```
JWT_SECRET=change-me-to-a-long-random-string
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=1440
```

- [ ] **Step 4: 实现 `app/auth/security.py`**

```python
"""认证安全基元：bcrypt 密码哈希 + JWT 签发/校验。"""
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from app.config import settings

ALGORITHM = settings.jwt_algorithm
SECRET = settings.jwt_secret


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        return False


def create_access_token(user_id: int, role: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "role": role,
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_expire_minutes),
    }
    return jwt.encode(payload, SECRET, algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict:
    return jwt.decode(token, SECRET, algorithms=[ALGORITHM])
```

- [ ] **Step 5: 运行确认通过**

Run: `python -m pytest tests/test_security.py -v`
Expected: PASS（4 项）

- [ ] **Step 6: Commit**

```bash
git add requirements.txt app/config.py app/auth/ tests/test_security.py .env.example
git commit -m "feat(p1): JWT + bcrypt security primitives and settings"
```

---

### Task 2: 认证 API（login / me / 当前用户依赖）

**Files:**
- Create: `app/auth/deps.py`
- Create: `app/api/__init__.py`
- Create: `app/api/auth.py`
- Create: `app/schemas.py`
- Test: `tests/test_auth_api.py`

**Interfaces:**
- Consumes: `app.auth.security.*`（Task 1）、`app.models.User/UserRole`（P0）、`app.db.get_db`（P0）。
- Produces:
  - `app.auth.deps.get_current_user(token: str = Depends(oauth2_scheme), db = Depends(get_db)) -> User`（401 若无效/停用）
  - `app.auth.deps.require_role(*roles: str) -> Callable`（依赖工厂，403 若角色不符）
  - `app.schemas.UserOut`、`app.schemas.TokenOut`
  - `POST /api/auth/login` → `TokenOut`；`GET /api/auth/me` → `UserOut`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_auth_api.py
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.auth.security import hash_password
from app.db import Base, engine
from app.main import app  # 由 Task 5 组装；Task 2 用临时 app 亦可，见 Step 3 说明
from app.models import User


@pytest.fixture()
def client(db_session):
    # 见 Task 2 说明：Task 2 先建一个最小 app 挂 auth 路由供测试；
    # Task 5 合并进 app.main 后此 fixture 改 import app.main
    ...
```

> 注：Task 2 与 Task 5 存在先后依赖——`app.main` 尚未存在。为让 Task 2 独立可测，Step 3 会先建一个 `tests/conftest.py` 内的最小 FastAPI `create_test_app()`（只挂 auth 路由 + 测试库），Task 5 合并后删除。计划里以「`app.main` 已存在」的口径写测试，实际测试里用 `create_test_app()` 过渡，最终 Task 5 统一。

- [ ] **Step 2: 运行确认失败**（`ModuleNotFoundError` / 路由 404）

- [ ] **Step 3: 实现 schemas + deps + 路由**

`app/schemas.py`：
```python
from datetime import datetime
from pydantic import BaseModel, ConfigDict

class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    username: str
    role: str
    customer_id: str | None
    display_name: str | None
    is_active: bool
    created_at: datetime

class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut
```

`app/auth/deps.py`：
```python
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.auth.security import decode_access_token
from app.db import get_db
from app.models import User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")

def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    cred = HTTPException(status.HTTP_401_UNAUTHORIZED, "无效或过期的凭证", headers={"WWW-Authenticate": "Bearer"})
    try:
        payload = decode_access_token(token)
    except Exception:
        raise cred
    user_id = payload.get("sub")
    if user_id is None:
        raise cred
    user = db.get(User, int(user_id))
    if user is None or not user.is_active:
        raise cred
    return user

def require_role(*roles: str):
    def checker(user: User = Depends(get_current_user)) -> User:
        if user.role.value not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "权限不足")
        return user
    return checker
```

`app/api/auth.py`：
```python
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user
from app.auth.security import create_access_token, verify_password
from app.db import get_db
from app.models import User
from app.schemas import TokenOut, UserOut

router = APIRouter(prefix="/api/auth", tags=["auth"])

@router.post("/login", response_model=TokenOut)
def login(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == form.username).first()
    if user is None or not verify_password(form.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "用户名或密码错误")
    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "账号已停用")
    return TokenOut(access_token=create_access_token(user.id, user.role.value), user=UserOut.model_validate(user))

@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return UserOut.model_validate(user)
```

- [ ] **Step 4: 运行确认通过**（login 成功/密码错 401/停用 403；me 无 token 401、正确 token 200、伪造 token 401、require_role 403）

- [ ] **Step 5: Commit**

```bash
git add app/schemas.py app/auth/deps.py app/api/auth.py tests/test_auth_api.py
git commit -m "feat(p1): auth login/me + current-user dependencies"
```

---

### Task 3: 会话与消息 API（列表 / 创建 / 消息分页 + 归属校验）

**Files:**
- Create: `app/api/conversations.py`
- Modify: `app/schemas.py`（加 `ConversationOut`、`MessageOut`）
- Test: `tests/test_conversations_api.py`

**Interfaces:**
- Consumes: `app.auth.deps.get_current_user`（Task 2）、`app.models.Conversation/Message`（P0）、`app.db.get_db`（P0）。
- Produces:
  - `GET /api/conversations?limit=&offset=` → `list[ConversationOut]`（本人，按 updated_at 倒序）
  - `POST /api/conversations` → `ConversationOut`
  - `GET /api/conversations/{id}/messages?limit=&offset=` → `list[MessageOut]`（本人，按 id 升序；非本人 404）

- [ ] **Step 1: 写失败测试**

```python
# tests/test_conversations_api.py
def test_list_only_own_conversations(client, user_a, user_b, conv_a, conv_b):
    # user_a 登录 → GET /api/conversations 只含 conv_a，不含 conv_b

def test_cannot_read_others_messages(client, user_a, conv_b):
    # user_a 请求 conv_b（属于 user_b）的消息 → 404

def test_messages_paginated_ascending(client, user_a, conv_a_with_10_messages):
    # limit=3&offset=3 → 第 4..6 条，按 id 升序
```

- [ ] **Step 2: 运行确认失败**（路由 404）

- [ ] **Step 3: 实现 schemas + 路由**

`app/schemas.py` 追加：
```python
class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    conversation_id: int
    role: str
    content: str
    tool_call_id: str | None
    tool_calls: dict | None
    citations: dict | None
    feedback: dict | None
    created_at: datetime

class ConversationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    status: str
    created_at: datetime
    updated_at: datetime
```

`app/api/conversations.py`：
```python
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user
from app.db import get_db
from app.models import Conversation, Message, User
from app.schemas import ConversationOut, MessageOut

router = APIRouter(prefix="/api/conversations", tags=["conversations"])

@router.get("", response_model=list[ConversationOut])
def list_conversations(limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0),
                       db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = (db.query(Conversation).filter(Conversation.user_id == user.id)
            .order_by(Conversation.updated_at.desc()).limit(limit).offset(offset).all())
    return [ConversationOut.model_validate(r) for r in rows]

@router.post("", response_model=ConversationOut, status_code=status.HTTP_201_CREATED)
def create_conversation(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    conv = Conversation(user_id=user.id)
    db.add(conv); db.commit(); db.refresh(conv)
    return ConversationOut.model_validate(conv)

def _owned_conversation(conv_id: int, user: User, db: Session) -> Conversation:
    conv = db.get(Conversation, conv_id)
    if conv is None or conv.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "会话不存在")
    return conv

@router.get("/{conv_id}/messages", response_model=list[MessageOut])
def list_messages(conv_id: int, limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
                  db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _owned_conversation(conv_id, user, db)
    rows = (db.query(Message).filter(Message.conversation_id == conv_id)
            .order_by(Message.id.asc()).limit(limit).offset(offset).all())
    return [MessageOut.model_validate(r) for r in rows]
```

- [ ] **Step 4: 运行确认通过**（越权 404、列表隔离、分页升序）

- [ ] **Step 5: Commit**

```bash
git add app/api/conversations.py app/schemas.py tests/test_conversations_api.py
git commit -m "feat(p1): conversations list/create + paginated messages with ownership"
```

---

### Task 4: SSE 聊天流底座 + 反馈

**Files:**
- Create: `app/api/chat.py`
- Modify: `app/schemas.py`（加 `ChatStreamRequest`、`FeedbackRequest`）
- Test: `tests/test_chat_stream.py`

**Interfaces:**
- Consumes: `app.auth.deps.get_current_user`（Task 2）、`_owned_conversation`（Task 3，导出复用）、`app.models.Message/Conversation`（P0）。
- Produces:
  - `POST /api/chat/stream` → `StreamingResponse`（`text/event-stream`），事件 `status`→`text`→`done`（P1 占位；P3 替换生成逻辑，事件契约不变）
  - `POST /api/messages/{id}/feedback` → `MessageOut`（👍/👎 幂等单值）
  - 事件编码工具 `app/api/chat.py:sse_event(event: str, data: dict) -> str`（`event: <e>\ndata: <json>\n\n`）

- [ ] **Step 1: 写失败测试**

```python
# tests/test_chat_stream.py
def test_stream_emits_status_text_done_and_persists(client, user_a, conv_a):
    with client.stream("POST", "/api/chat/stream", json={"conversation_id": conv_a.id, "content": "你好"}) as r:
        assert r.status_code == 200
        events = parse_sse(r.iter_lines())
    assert [e.type for e in events] == ["status", "text", "done"]
    # 断言 messages 表里出现 user 消息 + assistant 消息各一条

def test_stream_on_others_conversation_404(client, user_a, conv_b):
    with client.stream("POST", "/api/chat/stream", json={"conversation_id": conv_b.id, "content": "x"}) as r:
        assert r.status_code == 404
    # 断言未产生任何消息

def test_feedback_idempotent(client, user_a, msg_a):
    client.post(f"/api/messages/{msg_a.id}/feedback", json={"type": "up"})
    client.post(f"/api/messages/{msg_a.id}/feedback", json={"type": "up"})
    # 断言 feedback 仍为单值 {"type": "up", ...}，无重复行
```

- [ ] **Step 2: 运行确认失败**（路由 404）

- [ ] **Step 3: 实现**

`app/schemas.py` 追加：
```python
class ChatStreamRequest(BaseModel):
    conversation_id: int
    content: str

class FeedbackRequest(BaseModel):
    type: str  # "up" | "down"
```

`app/api/chat.py`：
```python
import json
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user
from app.api.conversations import _owned_conversation
from app.db import get_db
from app.models import Conversation, Message, User
from app.schemas import ChatStreamRequest, FeedbackRequest, MessageOut

router = APIRouter(prefix="/api", tags=["chat"])

P1_PLACEHOLDER = "你好，我是 SayHelp 客服助手。当前为 P1 骨架阶段，完整问答将在后续阶段接入。"

def sse_event(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

@router.post("/chat/stream")
def chat_stream(req: ChatStreamRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    conv = _owned_conversation(req.conversation_id, user, db)
    user_msg = Message(conversation_id=conv.id, role="user", content=req.content)
    db.add(user_msg); db.commit()

    def gen():
        yield sse_event("status", {"state": "processing"})
        yield sse_event("text", {"delta": P1_PLACEHOLDER})
        yield sse_event("done", {})

    # 占位回答在流结束后落库为 assistant 消息（P3 会在生成侧落库）
    assistant = Message(conversation_id=conv.id, role="assistant", content=P1_PLACEHOLDER)
    db.add(assistant); db.commit()
    return StreamingResponse(gen(), media_type="text/event-stream")

@router.post("/messages/{message_id}/feedback", response_model=MessageOut)
def feedback(message_id: int, req: FeedbackRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    msg = db.get(Message, message_id)
    if msg is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "消息不存在")
    conv = _owned_conversation(msg.conversation_id, user, db)
    if req.type not in ("up", "down"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "type 须为 up/down")
    msg.feedback = {"type": req.type, "at": datetime.utcnow().isoformat()}
    db.commit(); db.refresh(msg)
    return MessageOut.model_validate(msg)
```

> 注：`_owned_conversation` 以 `_` 前缀命名仍被跨模块导入——更名 `get_owned_conversation` 并保留在 `app/api/conversations.py`，`__init__` 不动。本计划正文沿用原名以对齐 Task 3，实现时统一为 `get_owned_conversation`。

- [ ] **Step 4: 运行确认通过**（事件顺序、落库、越权 404、反馈幂等）

- [ ] **Step 5: Commit**

```bash
git add app/api/chat.py app/schemas.py tests/test_chat_stream.py
git commit -m "feat(p1): SSE chat stream skeleton + idempotent feedback"
```

---

### Task 5: FastAPI 组装、静态资源、健康检查

**Files:**
- Create: `app/main.py`
- Modify: `app/api/__init__.py`（导出各 router）
- Create: `web/index.html`（占位，Task 6 完善）
- Test: `tests/test_app.py`

**Interfaces:**
- Consumes: Task 2/3/4 的 routers、`app.config.settings`。
- Produces: `app.main:app`（FastAPI 实例，挂 auth/conversations/chat 路由 + `GET /healthz` + 静态 `/`）。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_app.py
def test_healthz(client):
    assert client.get("/healthz").json() == {"status": "ok"}

def test_static_index_served(client):
    r = client.get("/")
    assert r.status_code == 200 and "text/html" in r.headers["content-type"]
```

- [ ] **Step 2: 运行确认失败**（无 app）

- [ ] **Step 3: 实现 `app/main.py`**

```python
from pathlib import Path
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api import auth, chat, conversations

app = FastAPI(title="SayHelp", version="0.1.0")

app.include_router(auth.router)
app.include_router(conversations.router)
app.include_router(chat.router)

@app.get("/healthz")
def healthz():
    return {"status": "ok"}

WEB_DIR = Path(__file__).resolve().parents[1] / "web"
app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")
```

- [ ] **Step 4: 运行确认通过**；将 Task 2 的过渡 `create_test_app()` 替换为 `app.main.app`（`tests/conftest.py` 统一）

- [ ] **Step 5: Commit**

```bash
git add app/main.py app/api/__init__.py web/index.html tests/test_app.py tests/conftest.py
git commit -m "feat(p1): FastAPI app assembly, static serving, health check"
```

---

### Task 6: 前端（登录 + 聊天 + 历史 + 卡片骨架）

**Files:**
- Create: `web/index.html`、`web/chat.html`、`web/app.js`、`web/style.css`
- Test: `tests/test_static_assets.py`（静态资源可达性；JS 逻辑走人工验收）

**Interfaces:**
- Consumes: `POST /api/auth/login`、`GET /api/conversations`、`GET /api/conversations/{id}/messages`、`POST /api/chat/stream`（SSE）。
- Produces: 可浏览器运行的登录 + 聊天前端；`parseSse(stream)` 工具函数解析 POST 型 SSE；`renderCard(card)` 骨架（订单选择/建工单预览占位，P4 接真实数据）。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_static_assets.py
def test_static_assets_reachable(client):
    for path in ["/", "/app.js", "/style.css", "/chat.html"]:
        assert client.get(path).status_code == 200
```

- [ ] **Step 2: 运行确认失败**（文件不存在 → 404）

- [ ] **Step 3: 实现前端**

`web/app.js` 关键逻辑（登录存 localStorage JWT → 拉会话列表 → POST 型 SSE 用 `fetch`+`ReadableStream` 逐事件解析 `event:`/`data:` 行）：

```javascript
async function login(username, password) {
  const fd = new URLSearchParams({ username, password });
  const r = await fetch("/api/auth/login", { method: "POST", body: fd,
    headers: { "Content-Type": "application/x-www-form-urlencoded" } });
  if (!r.ok) throw new Error("登录失败");
  const data = await r.json();
  localStorage.setItem("sayhelp_token", data.access_token);
  return data.user;
}

async function chatStream(conversationId, content, onEvent) {
  const r = await fetch("/api/chat/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json",
      "Authorization": "Bearer " + localStorage.getItem("sayhelp_token") },
    body: JSON.stringify({ conversation_id: conversationId, content }),
  });
  const reader = r.body.getReader();
  const dec = new TextDecoder();
  let buf = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    // 按 "\n\n" 切事件块，解析 event:/data: 行，调用 onEvent(type, data)
  }
}

function renderCard(card) {
  // 骨架：card.type === "order_select" → 订单选择卡片；"ticket_preview" → 建工单预览卡片
  // P4 接入真实数据前仅渲染占位结构。
}
```

- [ ] **Step 4: 运行确认通过**（静态可达性）；人工验收登录→聊天→历史→SSE 逐字渲染

- [ ] **Step 5: Commit**

```bash
git add web/ tests/test_static_assets.py
git commit -m "feat(p1): native frontend login/chat/history + card skeleton"
```

---

## 完成契约

P1 全部 6 任务完成后：`python -m pytest` 全绿；`uvicorn app.main:app` 可启动；浏览器登录（admin/SayHelp123!）→ 建会话 → 发消息 → SSE 逐字显示占位回答 → 历史列表与消息回显正常。`resume` 端点与真实 interrupt/卡片数据留待 P4。
